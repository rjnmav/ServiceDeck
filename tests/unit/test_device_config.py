"""Unit tests for remote device configuration storage."""

import stat
from pathlib import Path

from servicedeck.backend.remote.device_config import DeviceConfigManager, RemoteDevice


def test_remote_device_serialization() -> None:
    device = RemoteDevice(
        id="srv1",
        display_name="Server 1",
        hostname="srv1.example.com",
        port=2222,
        username="admin",
        ssh_key_path="/home/user/.ssh/id_ed25519",
    )
    data = device.to_dict()
    assert data["id"] == "srv1"
    assert data["port"] == 2222
    assert data["username"] == "admin"

    loaded = RemoteDevice.from_dict(data)
    assert loaded == device


def test_device_config_manager_empty(tmp_path: Path) -> None:
    config_file = tmp_path / "devices.json"
    mgr = DeviceConfigManager(config_path=config_file)
    assert mgr.load_devices() == []
    assert mgr.get_device("srv1") is None


def test_device_config_manager_save_and_load(tmp_path: Path) -> None:
    config_file = tmp_path / "devices.json"
    mgr = DeviceConfigManager(config_path=config_file)

    dev1 = RemoteDevice(id="srv1", display_name="S1", hostname="srv1.test")
    dev2 = RemoteDevice(id="srv2", display_name="S2", hostname="srv2.test", port=222)

    mgr.save_device(dev1)
    mgr.save_device(dev2)

    devices = mgr.load_devices()
    assert len(devices) == 2
    assert mgr.get_device("srv1") == dev1
    assert mgr.get_device("srv2") == dev2

    # Check file permissions are restricted to 0600
    file_stat = config_file.stat()
    assert stat.S_IMODE(file_stat.st_mode) == 0o600


def test_device_config_manager_update_device(tmp_path: Path) -> None:
    config_file = tmp_path / "devices.json"
    mgr = DeviceConfigManager(config_path=config_file)

    dev1 = RemoteDevice(id="srv1", display_name="Old Name", hostname="srv1.test")
    mgr.save_device(dev1)

    updated_dev1 = RemoteDevice(id="srv1", display_name="New Name", hostname="srv1.test", port=2200)
    mgr.save_device(updated_dev1)

    devices = mgr.load_devices()
    assert len(devices) == 1
    assert devices[0].display_name == "New Name"
    assert devices[0].port == 2200


def test_device_config_manager_remove_device(tmp_path: Path) -> None:
    config_file = tmp_path / "devices.json"
    mgr = DeviceConfigManager(config_path=config_file)

    dev1 = RemoteDevice(id="srv1", display_name="S1", hostname="srv1.test")
    dev2 = RemoteDevice(id="srv2", display_name="S2", hostname="srv2.test")
    mgr.save_device(dev1)
    mgr.save_device(dev2)

    assert mgr.remove_device("srv1") is True
    assert mgr.remove_device("srv1") is False  # Already removed
    assert len(mgr.load_devices()) == 1
    assert mgr.get_device("srv1") is None
    assert mgr.get_device("srv2") == dev2
