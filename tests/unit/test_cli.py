"""Unit tests for the ServiceDeck CLI dispatcher."""

import dataclasses
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.cli import main


def test_cli_remote_subcommand_message(capsys: pytest.CaptureFixture) -> None:
    """Invoking 'servicedeck remote' prints Phase 2 informational guidance."""
    exit_code = main(["remote"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert "Phase 2" in captured.err


def test_cli_backend_dispatches_with_defaults() -> None:
    """Invoking 'servicedeck backend' calls backend main with forwarded arguments."""
    with patch("servicedeck.backend.main.main", return_value=0) as mock_backend:
        exit_code = main(["backend", "--port", "8888"])
        assert exit_code == 0
        mock_backend.assert_called_once_with(["--port", "8888"])


def test_cli_remote_add_and_list(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    """Invoking 'servicedeck remote add' and 'servicedeck remote list'."""
    test_device = RemoteDevice(id="srv1", display_name="srv1", hostname="1.2.3.4", port=22)
    mock_mgr = MagicMock()
    mock_mgr.load_devices.return_value = [test_device]

    with patch(
        "servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr
    ):
        # Test add
        add_code = main(["remote", "add", "srv1", "1.2.3.4"])
        assert add_code == 0
        mock_mgr.save_device.assert_called_once()
        out = capsys.readouterr().out
        assert "added successfully" in out

        # Test list
        list_code = main(["remote", "list"])
        assert list_code == 0
        out = capsys.readouterr().out
        assert "srv1" in out
        assert "1.2.3.4" in out


def test_cli_remote_remove(capsys: pytest.CaptureFixture) -> None:
    mock_mgr = MagicMock()
    mock_mgr.remove_device.side_effect = [True, False]

    with patch(
        "servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr
    ):
        assert main(["remote", "remove", "srv1"]) == 0
        assert "removed successfully" in capsys.readouterr().out

        assert main(["remote", "remove", "srv1"]) == 1
        assert "not found" in capsys.readouterr().err


def test_cli_remote_status(capsys: pytest.CaptureFixture) -> None:
    test_device = RemoteDevice(id="srv1", display_name="Server 1", hostname="1.2.3.4", port=22)
    mock_mgr = MagicMock()
    mock_mgr.get_device.side_effect = lambda dev_id: test_device if dev_id == "srv1" else None

    with patch(
        "servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr
    ):
        assert main(["remote", "status", "srv1"]) == 0
        out = capsys.readouterr().out
        assert "Server 1" in out
        assert "1.2.3.4:22" in out

        assert main(["remote", "status", "unknown"]) == 1
        assert "not found" in capsys.readouterr().err


def _setup_key_mocks(monkeypatch: pytest.MonkeyPatch, status: str) -> dict:
    from servicedeck.backend.remote import key_setup
    from servicedeck.backend.remote.key_setup import KeySetupResult
    from servicedeck.backend.remote.keys import LoginKey
    from servicedeck.backend.remote.known_hosts import HostKeyInfo, KnownHostsStore

    calls: dict = {"trusted": [], "setup": []}
    info = HostKeyInfo("1.2.3.4", 22, status, "ssh-ed25519", "SHA256:abc")  # type: ignore[arg-type]

    async def fake_check(self, host, port):
        return info

    async def fake_trust(self, host, port, fingerprint):
        calls["trusted"].append(fingerprint)
        return info

    async def fake_setup(device, password, **kwargs):
        calls["setup"].append(password)
        key = LoginKey(
            Path("/k/id_ed25519"), "ssh-ed25519", "AAAA", "servicedeck@pc", "SHA256:k", True
        )
        return KeySetupResult(
            device=dataclasses.replace(device, ssh_key_path=str(key.private_path)),
            key=key,
            added=True,
        )

    monkeypatch.setattr(KnownHostsStore, "check", fake_check)
    monkeypatch.setattr(KnownHostsStore, "trust", fake_trust)
    monkeypatch.setattr(key_setup, "setup_key", fake_setup)
    monkeypatch.setattr("getpass.getpass", lambda prompt: "pw-123")
    return calls


def test_remote_setup_key_trusts_host_and_installs_key(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls = _setup_key_mocks(monkeypatch, "unknown")
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    device = RemoteDevice(id="srv1", display_name="srv1", hostname="1.2.3.4", username="alice")

    with patch("servicedeck.backend.remote.device_config.DeviceConfigManager") as mgr_cls:
        mgr = mgr_cls.return_value
        mgr.get_device.return_value = device
        assert main(["remote", "setup-key", "srv1"]) == 0

    assert calls == {"trusted": ["SHA256:abc"], "setup": ["pw-123"]}
    saved = mgr.save_device.call_args.args[0]
    assert saved.ssh_key_path == "/k/id_ed25519"
    out = capsys.readouterr().out
    assert "SHA256:abc" in out and "pw-123" not in out


def test_remote_setup_key_declined_host_key_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _setup_key_mocks(monkeypatch, "unknown")
    monkeypatch.setattr("builtins.input", lambda prompt: "n")
    device = RemoteDevice(id="srv1", display_name="srv1", hostname="1.2.3.4")

    with patch("servicedeck.backend.remote.device_config.DeviceConfigManager") as mgr_cls:
        mgr_cls.return_value.get_device.return_value = device
        assert main(["remote", "setup-key", "srv1"]) == 1
        mgr_cls.return_value.save_device.assert_not_called()

    assert calls == {"trusted": [], "setup": []}
