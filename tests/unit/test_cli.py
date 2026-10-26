"""Unit tests for the ServiceDeck CLI dispatcher."""

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

    with patch("servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr):
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

    with patch("servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr):
        assert main(["remote", "remove", "srv1"]) == 0
        assert "removed successfully" in capsys.readouterr().out

        assert main(["remote", "remove", "srv1"]) == 1
        assert "not found" in capsys.readouterr().err


def test_cli_remote_status(capsys: pytest.CaptureFixture) -> None:
    test_device = RemoteDevice(id="srv1", display_name="Server 1", hostname="1.2.3.4", port=22)
    mock_mgr = MagicMock()
    mock_mgr.get_device.side_effect = lambda dev_id: test_device if dev_id == "srv1" else None

    with patch("servicedeck.backend.remote.device_config.DeviceConfigManager", return_value=mock_mgr):
        assert main(["remote", "status", "srv1"]) == 0
        out = capsys.readouterr().out
        assert "Server 1" in out
        assert "1.2.3.4:22" in out

        assert main(["remote", "status", "unknown"]) == 1
        assert "not found" in capsys.readouterr().err
