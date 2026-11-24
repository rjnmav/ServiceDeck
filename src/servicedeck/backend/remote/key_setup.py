"""One-time, password-authenticated installation of an SSH login key (like ``ssh-copy-id``).

Flow: the host key must already be trusted -> log in once with the account password ->
append the login key to ``~/.ssh/authorized_keys`` -> prove that the key alone now works.

The password is used for that single login only. It is never stored, logged, or put
into exception messages or details.
"""

from __future__ import annotations

import asyncio
import dataclasses
import logging
from dataclasses import dataclass
from typing import Any

import asyncssh

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteKeySetupError,
    SSHAuthenticationError,
)
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.keys import LoginKey, ServiceDeckKeyStore
from servicedeck.backend.remote.known_hosts import KnownHostsStore

logger = logging.getLogger(__name__)

# POSIX sh, run as `exec sh -c '<script>'` so the remote login shell does not matter.
# It must stay a single line without single quotes or `!`, so it survives any shell's
# quoting (csh included). The key arrives on stdin, never on the command line.
_INSTALL_SCRIPT = "; ".join(
    (
        "umask 077",
        'd="$HOME/.ssh"',
        'f="$d/authorized_keys"',
        '{ mkdir -p "$d" && chmod 700 "$d"; } || exit 11',
        '{ touch "$f" && chmod 600 "$f"; } || exit 12',
        "IFS= read -r blob || exit 13",
        "IFS= read -r line || exit 13",
        'if [ -s "$f" ] && [ -n "$(tail -c 1 "$f")" ]; then printf "\\n" >> "$f"; fi',
        'if grep -qF -- "$blob" "$f"; then echo present; '
        'else { printf "%s\\n" "$line" >> "$f"; } || exit 14; echo added; fi',
        "if command -v restorecon >/dev/null 2>&1; then "
        'restorecon -F "$d" "$f" >/dev/null 2>&1 || true; fi',
    )
)
assert "'" not in _INSTALL_SCRIPT and "\n" not in _INSTALL_SCRIPT and "!" not in _INSTALL_SCRIPT

INSTALL_COMMAND = f"exec sh -c '{_INSTALL_SCRIPT}'"

_INSTALL_FAILURES = {
    11: "could not create ~/.ssh",
    12: "could not create or update ~/.ssh/authorized_keys",
    13: "did not receive the public key",
    14: "could not append to ~/.ssh/authorized_keys",
}

_DEFAULT_TIMEOUT = 20.0


@dataclass(frozen=True, slots=True)
class KeySetupResult:
    """Outcome of a successful key installation."""

    device: RemoteDevice
    key: LoginKey
    added: bool


async def _connect(
    device: RemoteDevice,
    known_hosts: KnownHostsStore,
    timeout: float,
    **auth: Any,
) -> asyncssh.SSHClientConnection:
    target = f"{device.username + '@' if device.username else ''}{device.hostname}"
    try:
        return await asyncio.wait_for(
            asyncssh.connect(
                host=device.hostname,
                port=device.port,
                username=device.username,
                known_hosts=known_hosts.paths(),
                agent_forwarding=False,
                **auth,
            ),
            timeout=timeout,
        )
    except asyncssh.HostKeyNotVerifiable as exc:
        info = await known_hosts.check(device.hostname, device.port)
        raise known_hosts.unverified_error(info) from exc
    except asyncssh.PermissionDenied as exc:
        raise SSHAuthenticationError(
            f"SSH login to {target} was rejected",
            details={"hostname": device.hostname},
        ) from exc
    except TimeoutError as exc:
        raise RemoteConnectionError(
            f"Connection timeout after {timeout}s to {device.hostname}:{device.port}",
            details={"hostname": device.hostname},
        ) from exc
    except (asyncssh.Error, OSError) as exc:
        raise RemoteConnectionError(
            f"SSH connection failed to {device.hostname}:{device.port}: {exc}",
            details={"hostname": device.hostname},
        ) from exc


async def _close(conn: asyncssh.SSHClientConnection) -> None:
    conn.close()
    try:
        await conn.wait_closed()
    except Exception as exc:
        logger.debug("SSH connection closure finished with: %s", exc)


async def setup_key(
    device: RemoteDevice,
    password: str,
    *,
    key_store: ServiceDeckKeyStore | None = None,
    known_hosts: KnownHostsStore | None = None,
    timeout: float = _DEFAULT_TIMEOUT,
) -> KeySetupResult:
    """Install the device's login key on the remote host using a one-time password login.

    Returns the device with ``ssh_key_path`` pointing at the installed key; the caller
    persists it.
    """
    key_store = key_store or ServiceDeckKeyStore()
    known_hosts = known_hosts or KnownHostsStore()

    info = await known_hosts.check(device.hostname, device.port)
    if info.status != "trusted":
        raise known_hosts.unverified_error(info)

    key = key_store.key_for_device(device)

    conn = await _connect(
        device,
        known_hosts,
        timeout,
        password=password,
        client_keys=None,
        agent_path=None,
        preferred_auth="keyboard-interactive,password",
    )
    del password
    try:
        result = await asyncio.wait_for(
            conn.run(
                INSTALL_COMMAND,
                input=f"{key.blob}\n{key.authorized_keys_line()}\n",
                check=False,
            ),
            timeout=timeout,
        )
    except (asyncssh.Error, OSError, TimeoutError) as exc:
        raise RemoteKeySetupError(
            f"Installing the SSH key on {device.hostname} failed: {exc}",
            details={"hostname": device.hostname},
        ) from exc
    finally:
        await _close(conn)

    stdout = str(result.stdout or "")
    stderr = str(result.stderr or "").strip()
    if result.exit_status != 0:
        reason = _INSTALL_FAILURES.get(
            result.exit_status or -1, f"install script exited with status {result.exit_status}"
        )
        raise RemoteKeySetupError(
            f"Could not install the SSH key on {device.hostname}: {reason}"
            + (f" ({stderr.splitlines()[-1]})" if stderr else ""),
            details={
                "hostname": device.hostname,
                "exit_status": result.exit_status,
                "stderr": stderr,
            },
        )
    added = "added" in stdout.split()

    # Prove the key alone works, with no password and no agent to mask a failure.
    try:
        verify = await _connect(
            device,
            known_hosts,
            timeout,
            client_keys=[str(key.private_path)],
            password=None,
            agent_path=None,
            preferred_auth="publickey",
        )
    except SSHAuthenticationError as exc:
        raise RemoteKeySetupError(
            f"The key was added to ~/.ssh/authorized_keys on {device.hostname}, but the server "
            "still refuses it. The server may use a custom AuthorizedKeysFile or have "
            "PubkeyAuthentication disabled; check /etc/ssh/sshd_config there.",
            details={"hostname": device.hostname, "key_fingerprint": key.fingerprint},
        ) from exc
    await _close(verify)

    logger.info(
        "SSH key %s %s on %s",
        key.fingerprint,
        "installed" if added else "already present",
        device.hostname,
    )
    return KeySetupResult(
        device=dataclasses.replace(device, ssh_key_path=str(key.private_path)),
        key=key,
        added=added,
    )


__all__ = ["INSTALL_COMMAND", "KeySetupResult", "setup_key"]
