"""Unit tests for SSH onboarding: login key store, host-key trust, and key installation."""

import logging
import os
import stat
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from servicedeck.backend.exceptions import (
    RemoteHostKeyChangedError,
    RemoteHostKeyUnknownError,
    RemoteKeySetupError,
    SSHAuthenticationError,
)
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.key_setup import INSTALL_COMMAND, setup_key
from servicedeck.backend.remote.keys import ServiceDeckKeyStore, load_user_key
from servicedeck.backend.remote.known_hosts import (
    HostKeyInfo,
    KnownHostsStore,
    known_hosts_pattern,
)

PASSWORD = "correct horse battery staple"


def _mode(path: Path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


@pytest.fixture
def device() -> RemoteDevice:
    return RemoteDevice(id="srv", display_name="Srv", hostname="srv.test", username="alice")


@pytest.fixture
def store(tmp_path: Path) -> KnownHostsStore:
    return KnownHostsStore(path=tmp_path / "kh" / "known_hosts", extra_paths=[])


@pytest.fixture
def key_store(tmp_path: Path) -> ServiceDeckKeyStore:
    return ServiceDeckKeyStore(directory=tmp_path / "ssh")


def _serve_host_key(monkeypatch: pytest.MonkeyPatch, key: asyncssh.SSHKey) -> None:
    async def fake_get_server_host_key(host: str, port: int) -> asyncssh.SSHKey:
        return key.convert_to_public()

    monkeypatch.setattr(asyncssh, "get_server_host_key", fake_get_server_host_key)


# --- Login key store ---


def test_dedicated_key_is_generated_once_with_private_permissions(
    key_store: ServiceDeckKeyStore,
) -> None:
    first = key_store.ensure_key()
    second = key_store.ensure_key()

    assert first == second
    assert first.dedicated is True
    assert first.algorithm == "ssh-ed25519"
    assert first.comment.startswith("servicedeck@")
    assert first.fingerprint.startswith("SHA256:")
    assert _mode(key_store.private_path) == 0o600
    assert _mode(key_store.private_path.parent) == 0o700
    assert first.authorized_keys_line() == f"restrict ssh-ed25519 {first.blob} {first.comment}"


def test_chosen_user_key_is_used_without_restrict(
    tmp_path: Path, key_store: ServiceDeckKeyStore, device: RemoteDevice
) -> None:
    private = tmp_path / "id_mine"
    key = asyncssh.generate_private_key("ssh-ed25519", comment="me@laptop")
    key.write_private_key(private)
    key.write_public_key(f"{private}.pub")

    chosen = key_store.key_for_device(
        RemoteDevice(id="x", display_name="X", hostname="x", ssh_key_path=str(private))
    )
    assert chosen.dedicated is False
    assert chosen.private_path == private
    assert chosen.authorized_keys_line() == f"ssh-ed25519 {chosen.blob} me@laptop"
    assert not key_store.private_path.exists()  # dedicated key not generated needlessly


def test_encrypted_user_key_without_pub_gives_clear_error(tmp_path: Path) -> None:
    private = tmp_path / "id_locked"
    # PKCS#8 encryption needs no bcrypt; asyncssh reports it like an encrypted OpenSSH key.
    asyncssh.generate_private_key("ssh-ed25519").write_private_key(
        private, format_name="pkcs8-pem", passphrase="s3cret"
    )

    with pytest.raises(RemoteKeySetupError, match="passphrase-protected"):
        load_user_key(private)


# --- Host-key trust store ---


def test_known_hosts_pattern() -> None:
    assert known_hosts_pattern("srv.test", 22) == "srv.test"
    assert known_hosts_pattern("srv.test", 2222) == "[srv.test]:2222"


async def test_host_key_unknown_then_trusted(
    store: KnownHostsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    host_key = asyncssh.generate_private_key("ssh-ed25519")
    _serve_host_key(monkeypatch, host_key)

    info = await store.check("srv.test", 2222)
    assert info.status == "unknown"
    assert info.fingerprint == host_key.get_fingerprint()

    trusted = await store.trust("srv.test", 2222, info.fingerprint)
    assert trusted.status == "trusted"
    line = store.path.read_text()
    assert line.startswith("[srv.test]:2222 ssh-ed25519 ")
    assert _mode(store.path) == 0o600
    assert (await store.check("srv.test", 2222)).status == "trusted"

    # Trusting again is a no-op, not a duplicate entry.
    await store.trust("srv.test", 2222, info.fingerprint)
    assert store.path.read_text() == line


async def test_trust_refuses_fingerprint_mismatch(
    store: KnownHostsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    _serve_host_key(monkeypatch, asyncssh.generate_private_key("ssh-ed25519"))

    with pytest.raises(RemoteHostKeyChangedError, match="changed while it was being confirmed"):
        await store.trust("srv.test", 22, "SHA256:not-what-the-server-has")
    assert store.path.read_text() == ""


async def test_changed_host_key_is_detected_and_never_replaced(
    store: KnownHostsStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    old_key = asyncssh.generate_private_key("ssh-ed25519")
    _serve_host_key(monkeypatch, old_key)
    await store.trust("srv.test", 22, old_key.get_fingerprint())
    before = store.path.read_text()

    new_key = asyncssh.generate_private_key("ssh-ed25519")
    _serve_host_key(monkeypatch, new_key)
    info = await store.check("srv.test", 22)
    assert info.status == "changed"
    assert isinstance(store.unverified_error(info), RemoteHostKeyChangedError)

    with pytest.raises(RemoteHostKeyChangedError, match="CHANGED"):
        await store.trust("srv.test", 22, new_key.get_fingerprint())
    assert store.path.read_text() == before


def test_paths_never_empty(store: KnownHostsStore) -> None:
    assert store.paths() == [str(store.path)]
    assert store.path.exists()


# --- Key installation ---


class _TrustedStore(KnownHostsStore):
    async def check(self, hostname: str, port: int) -> HostKeyInfo:
        return HostKeyInfo(hostname, port, "trusted", "ssh-ed25519", "SHA256:host")


def _conn(run_result: object | None = None) -> MagicMock:
    conn = MagicMock()
    conn.run = AsyncMock(return_value=run_result)
    conn.wait_closed = AsyncMock()
    return conn


async def test_setup_key_installs_and_verifies(
    tmp_path: Path, device: RemoteDevice, key_store: ServiceDeckKeyStore
) -> None:
    trusted = _TrustedStore(path=tmp_path / "kh", extra_paths=[])
    install_conn = _conn(SimpleNamespace(exit_status=0, stdout="added\n", stderr=""))
    verify_conn = _conn()

    with patch("asyncssh.connect", new_callable=AsyncMock) as connect:
        connect.side_effect = [install_conn, verify_conn]
        result = await setup_key(device, PASSWORD, key_store=key_store, known_hosts=trusted)

    key = key_store.ensure_key()
    assert result.added is True
    assert result.device.ssh_key_path == str(key_store.private_path)

    login_kwargs = connect.call_args_list[0].kwargs
    assert login_kwargs["password"] == PASSWORD
    assert login_kwargs["client_keys"] is None and login_kwargs["agent_path"] is None
    assert login_kwargs["known_hosts"] == trusted.paths()

    command = install_conn.run.call_args.args[0]
    assert command == INSTALL_COMMAND
    assert key.blob not in command  # key travels on stdin, never on the command line
    assert install_conn.run.call_args.kwargs["input"] == (
        f"{key.blob}\n{key.authorized_keys_line()}\n"
    )

    verify_kwargs = connect.call_args_list[1].kwargs
    assert verify_kwargs["client_keys"] == [str(key_store.private_path)]
    assert verify_kwargs["password"] is None and verify_kwargs["agent_path"] is None


async def test_setup_key_requires_trusted_host_key(
    store: KnownHostsStore,
    device: RemoteDevice,
    key_store: ServiceDeckKeyStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _serve_host_key(monkeypatch, asyncssh.generate_private_key("ssh-ed25519"))
    with (
        patch("asyncssh.connect", new_callable=AsyncMock) as connect,
        pytest.raises(RemoteHostKeyUnknownError),
    ):
        await setup_key(device, PASSWORD, key_store=key_store, known_hosts=store)
    connect.assert_not_called()


async def test_setup_key_wrong_password_never_leaks_password(
    tmp_path: Path,
    device: RemoteDevice,
    key_store: ServiceDeckKeyStore,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    trusted = _TrustedStore(path=tmp_path / "kh", extra_paths=[])
    with patch("asyncssh.connect", new_callable=AsyncMock) as connect:
        connect.side_effect = asyncssh.PermissionDenied("Permission denied")
        with pytest.raises(SSHAuthenticationError) as info:
            await setup_key(device, PASSWORD, key_store=key_store, known_hosts=trusted)

    assert PASSWORD not in str(info.value)
    assert PASSWORD not in repr(info.value.details)
    assert PASSWORD not in caplog.text


async def test_setup_key_reports_install_failure(
    tmp_path: Path, device: RemoteDevice, key_store: ServiceDeckKeyStore
) -> None:
    trusted = _TrustedStore(path=tmp_path / "kh", extra_paths=[])
    failing = _conn(
        SimpleNamespace(exit_status=11, stdout="", stderr="mkdir: Read-only file system")
    )
    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=failing):
        with pytest.raises(RemoteKeySetupError, match=r"could not create ~/\.ssh"):
            await setup_key(device, PASSWORD, key_store=key_store, known_hosts=trusted)


async def test_setup_key_reports_key_still_refused(
    tmp_path: Path, device: RemoteDevice, key_store: ServiceDeckKeyStore
) -> None:
    trusted = _TrustedStore(path=tmp_path / "kh", extra_paths=[])
    install_conn = _conn(SimpleNamespace(exit_status=0, stdout="added\n", stderr=""))
    with patch("asyncssh.connect", new_callable=AsyncMock) as connect:
        connect.side_effect = [install_conn, asyncssh.PermissionDenied("nope")]
        with pytest.raises(RemoteKeySetupError, match="AuthorizedKeysFile"):
            await setup_key(device, PASSWORD, key_store=key_store, known_hosts=trusted)
