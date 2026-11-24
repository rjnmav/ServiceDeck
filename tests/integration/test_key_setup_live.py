"""End-to-end SSH onboarding against a real (in-process) SSH server.

The server is asyncssh, listening on 127.0.0.1 with a password account. Commands run
through ``/bin/sh -c`` with ``HOME`` pointing at a temp dir, which is what sshd does
with the user's login shell. Key authentication reads the real authorized_keys file
the installer writes, honoring its options, including ``restrict``.

Covers: unknown host key -> trust -> one-time password key setup -> key-only login
-> no duplicate on re-run -> bundled agent started over the key-authenticated session.
"""

import asyncio
import contextlib
import os
import stat
from pathlib import Path
from typing import Any

import asyncssh
import pytest

from servicedeck.backend.exceptions import RemoteHostKeyUnknownError, SSHAuthenticationError
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.key_setup import setup_key
from servicedeck.backend.remote.keys import ServiceDeckKeyStore
from servicedeck.backend.remote.known_hosts import KnownHostsStore
from servicedeck.backend.remote.transport import SSHTransport

PASSWORD = "integration-password"


class _Server(asyncssh.SSHServer):
    def __init__(self, home: Path) -> None:
        self._home = home
        self._conn: asyncssh.SSHServerConnection | None = None

    def connection_made(self, conn: asyncssh.SSHServerConnection) -> None:
        self._conn = conn

    def begin_auth(self, username: str) -> bool:
        keys_file = self._home / ".ssh" / "authorized_keys"
        if self._conn is not None and keys_file.is_file() and keys_file.stat().st_size:
            self._conn.set_authorized_keys(str(keys_file))
        return True

    def password_auth_supported(self) -> bool:
        return True

    def validate_password(self, username: str, password: str) -> bool:
        return password == PASSWORD


async def _pump(reader: Any, write: Any, close: Any = None) -> None:
    """Copy a stream until EOF. Like sshd, a peer closing its channel only ends this copy."""
    try:
        while data := await reader.read(65536):
            write(data)
    except (BrokenPipeError, ConnectionError, asyncssh.Error):
        pass
    finally:
        if close is not None:
            with contextlib.suppress(Exception):
                close()


async def _run_command(
    process: asyncssh.SSHServerProcess,
    home: Path,
    children: list[asyncio.subprocess.Process],
    env_overrides: dict[str, str],
) -> None:
    env = {**os.environ, "HOME": str(home), **env_overrides}
    local = await asyncio.create_subprocess_exec(
        "/bin/sh",
        "-c",
        process.command or "",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    children.append(local)
    assert local.stdin is not None and local.stdout is not None and local.stderr is not None
    stdin_task = asyncio.create_task(_pump(process.stdin, local.stdin.write, local.stdin.close))
    await asyncio.gather(
        _pump(local.stdout, process.stdout.write), _pump(local.stderr, process.stderr.write)
    )
    status = await local.wait()
    stdin_task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await stdin_task
    with contextlib.suppress(Exception):
        process.exit(status)


@pytest.fixture
async def ssh_server(tmp_path: Path) -> Any:
    home = tmp_path / "remote-home"
    home.mkdir()
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    children: list[asyncio.subprocess.Process] = []
    env_overrides: dict[str, str] = {}
    server = await asyncssh.create_server(
        lambda: _Server(home),
        "127.0.0.1",
        0,
        server_host_keys=[host_key],
        process_factory=lambda p: _run_command(p, home, children, env_overrides),
        encoding=None,
    )
    port = server.sockets[0].getsockname()[1]
    try:
        yield {"port": port, "home": home, "host_key": host_key, "env": env_overrides}
    finally:
        server.close()
        await server.wait_closed()
        for child in children:
            if child.returncode is None:
                child.kill()
            await child.wait()


def _user_bus_available() -> bool:
    return bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")) or os.path.exists(
        f"/run/user/{os.getuid()}/bus"
    )


async def test_full_onboarding_against_real_ssh_server(tmp_path: Path, ssh_server: Any) -> None:
    port, home = ssh_server["port"], ssh_server["home"]
    known_hosts = KnownHostsStore(path=tmp_path / "local" / "known_hosts", extra_paths=[])
    key_store = ServiceDeckKeyStore(directory=tmp_path / "local" / "ssh")
    device = RemoteDevice(
        id="live", display_name="Live", hostname="127.0.0.1", port=port, username="tester"
    )

    # 1. First contact: host key is unknown; connecting fails closed with its fingerprint.
    info = await known_hosts.check("127.0.0.1", port)
    assert info.status == "unknown"
    assert info.fingerprint == ssh_server["host_key"].get_fingerprint()
    with pytest.raises(RemoteHostKeyUnknownError):
        await SSHTransport(device=device, known_hosts=known_hosts).connect(timeout=10)

    # 2. User confirms the fingerprint.
    await known_hosts.trust("127.0.0.1", port, info.fingerprint)
    assert (await known_hosts.check("127.0.0.1", port)).status == "trusted"

    # 3. Wrong password is rejected; nothing is written remotely.
    with pytest.raises(SSHAuthenticationError):
        await setup_key(device, "wrong", key_store=key_store, known_hosts=known_hosts)
    assert not (home / ".ssh").exists()

    # 4. Right password installs the key, ssh-copy-id style.
    result = await setup_key(device, PASSWORD, key_store=key_store, known_hosts=known_hosts)
    assert result.added is True
    authorized = home / ".ssh" / "authorized_keys"
    assert authorized.read_text() == result.key.authorized_keys_line() + "\n"
    assert authorized.read_text().startswith("restrict ssh-ed25519 ")
    assert stat.S_IMODE((home / ".ssh").stat().st_mode) == 0o700
    assert stat.S_IMODE(authorized.stat().st_mode) == 0o600

    # 5. Re-running is idempotent.
    again = await setup_key(device, PASSWORD, key_store=key_store, known_hosts=known_hosts)
    assert again.added is False
    assert authorized.read_text().count("ssh-ed25519") == 1

    # 6. Key-only login works (no password, no agent).
    conn = await asyncssh.connect(
        "127.0.0.1",
        port,
        username="tester",
        known_hosts=known_hosts.paths(),
        client_keys=[str(result.key.private_path)],
        agent_path=None,
        password=None,
    )
    assert (await conn.run("echo key-login-ok", check=True)).stdout.strip() == "key-login-ok"
    conn.close()
    await conn.wait_closed()


@pytest.mark.skipif(not _user_bus_available(), reason="No user D-Bus session available")
async def test_bundled_agent_runs_over_restricted_key_session(
    tmp_path: Path, ssh_server: Any
) -> None:
    """The `restrict`-ed key must still be able to run the bundled agent end to end."""
    port = ssh_server["port"]
    known_hosts = KnownHostsStore(path=tmp_path / "local" / "known_hosts", extra_paths=[])
    key_store = ServiceDeckKeyStore(directory=tmp_path / "local" / "ssh")
    device = RemoteDevice(
        id="live", display_name="Live", hostname="127.0.0.1", port=port, username="tester"
    )
    info = await known_hosts.check("127.0.0.1", port)
    await known_hosts.trust("127.0.0.1", port, info.fingerprint)
    result = await setup_key(device, PASSWORD, key_store=key_store, known_hosts=known_hosts)

    transport = SSHTransport(device=result.device, known_hosts=known_hosts)
    try:
        hello = await transport.connect(timeout=20)
        assert hello.uid == os.getuid()
        from servicedeck.remote.models import RequestMessage

        response = await transport.send_request(
            RequestMessage(id=1, method="service.list", params={"scope": "user"}), timeout=20
        )
        assert response.success is True
        assert isinstance(response.result, list) and response.result
    finally:
        await transport.disconnect()


# A stand-in for sudo that behaves like the real one on the wire: prompt on stderr without
# a newline, read the password byte by byte from stdin (the shell's `read` does that on a
# pipe), "Sorry, try again." on a wrong password, and exec the command once authorized.
_FAKE_SUDO = r"""#!/bin/sh
mode=""; prompt="Password:"
while [ $# -gt 0 ]; do
  case "$1" in
    -k) shift ;;
    -S) mode=S; shift ;;
    -n) mode=n; shift ;;
    -p) prompt="$2"; shift 2 ;;
    --) shift; break ;;
    *) break ;;
  esac
done
if [ "$mode" = n ]; then echo "sudo: a password is required" >&2; exit 1; fi
tries=0
while [ $tries -lt 3 ]; do
  printf '%s' "$prompt" >&2
  IFS= read -r pw || exit 1
  if [ "$pw" = "$FAKE_SUDO_PASSWORD" ]; then exec "$@"; fi
  echo "Sorry, try again." >&2
  tries=$((tries + 1))
done
echo "sudo: 3 incorrect password attempts" >&2
exit 1
"""


def _system_bus_available() -> bool:
    return os.path.exists("/run/dbus/system_bus_socket")


@pytest.mark.skipif(not _system_bus_available(), reason="No system D-Bus available")
async def test_sudo_elevation_runs_root_agent_over_the_same_connection(
    tmp_path: Path, ssh_server: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fake sudo can't make us root, so the uid the agent must report is the test's own."""
    from servicedeck.backend.exceptions import RemoteSudoAuthError
    from servicedeck.backend.remote.privileged import PrivilegedAgent
    from servicedeck.remote.models import RequestMessage

    monkeypatch.setattr(PrivilegedAgent, "required_uid", os.getuid())
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    sudo = bin_dir / "sudo"
    sudo.write_text(_FAKE_SUDO)
    sudo.chmod(0o755)
    ssh_server["env"].update(
        {"PATH": f"{bin_dir}:{os.environ['PATH']}", "FAKE_SUDO_PASSWORD": "sudo-pass"}
    )

    port = ssh_server["port"]
    known_hosts = KnownHostsStore(path=tmp_path / "local" / "known_hosts", extra_paths=[])
    key_store = ServiceDeckKeyStore(directory=tmp_path / "local" / "ssh")
    device = RemoteDevice(
        id="live", display_name="Live", hostname="127.0.0.1", port=port, username="tester"
    )
    info = await known_hosts.check("127.0.0.1", port)
    await known_hosts.trust("127.0.0.1", port, info.fingerprint)
    result = await setup_key(device, PASSWORD, key_store=key_store, known_hosts=known_hosts)

    transport = SSHTransport(device=result.device, known_hosts=known_hosts)
    try:
        await transport.connect(timeout=20)

        with pytest.raises(RemoteSudoAuthError) as needs_password:
            await transport.elevate(None, timeout=10)
        assert needs_password.value.details["password_required"] is True

        with pytest.raises(RemoteSudoAuthError):
            await transport.elevate("wrong", timeout=10)
        assert not transport.is_elevated

        hello = await transport.elevate("sudo-pass", timeout=20)
        assert hello.uid == os.getuid()
        assert transport.is_elevated

        response = await transport.send_privileged_request(
            RequestMessage(id=7, method="service.list", params={"scope": "system"}), timeout=20
        )
        assert response.success is True
        assert isinstance(response.result, list) and response.result

        # The normal agent is untouched and still answers on its own channel.
        assert (
            await transport.send_request(RequestMessage(id=8, method="health.check"), timeout=20)
        ).success

        await transport.drop_privileges()
        assert not transport.is_elevated
        assert transport.is_connected
    finally:
        await transport.disconnect()
