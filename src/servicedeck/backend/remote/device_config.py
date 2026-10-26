"""Device configuration storage for remote machines managed via SSH."""

from __future__ import annotations

import dataclasses
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "servicedeck" / "remote-devices.json"


@dataclass(frozen=True, slots=True)
class RemoteDevice:
    """Remote host connection configuration.

    This represents connection parameters only and is not proof of authorization.
    Sensitive credentials such as passwords or private keys are never stored here.
    """

    id: str
    display_name: str
    hostname: str
    port: int = 22
    username: str | None = None
    ssh_key_path: str | None = None

    def to_dict(self) -> dict[str, object]:
        """Convert dataclass to dictionary."""
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> RemoteDevice:
        """Construct RemoteDevice from dictionary."""
        return cls(
            id=str(data["id"]),
            display_name=str(data.get("display_name", data["id"])),
            hostname=str(data["hostname"]),
            port=int(data.get("port", 22)),
            username=str(data["username"]) if data.get("username") else None,
            ssh_key_path=str(data["ssh_key_path"]) if data.get("ssh_key_path") else None,
        )


class DeviceConfigManager:
    """Manages persistence of remote device metadata to ~/.config/servicedeck/remote-devices.json."""

    def __init__(self, config_path: Path | None = None) -> None:
        self._config_path = config_path or DEFAULT_CONFIG_PATH

    @property
    def config_path(self) -> Path:
        """Return the configuration file path."""
        return self._config_path

    def load_devices(self) -> list[RemoteDevice]:
        """Load and return all configured remote devices."""
        if not self._config_path.exists():
            return []

        try:
            with open(self._config_path, encoding="utf-8") as f:
                payload = json.load(f)

            devices_data = payload.get("devices", [])
            return [RemoteDevice.from_dict(d) for d in devices_data]
        except Exception as exc:
            logger.error("Failed to read device config from %s: %s", self._config_path, exc)
            return []

    def get_device(self, device_id: str) -> RemoteDevice | None:
        """Find a single device by its identifier."""
        devices = self.load_devices()
        for device in devices:
            if device.id == device_id:
                return device
        return None

    def save_device(self, device: RemoteDevice) -> None:
        """Add or update a remote device in persistent storage."""
        devices = self.load_devices()
        updated_devices = [d for d in devices if d.id != device.id]
        updated_devices.append(device)
        self._write_devices(updated_devices)

    def remove_device(self, device_id: str) -> bool:
        """Remove a remote device by id. Returns True if removed, False if not found."""
        devices = self.load_devices()
        filtered = [d for d in devices if d.id != device_id]
        if len(filtered) == len(devices):
            return False

        self._write_devices(filtered)
        return True

    def _write_devices(self, devices: list[RemoteDevice]) -> None:
        """Serialize devices list to configuration JSON file with restricted file permissions."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {"devices": [d.to_dict() for d in devices]}
        temp_file = self._config_path.with_suffix(".tmp")

        try:
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)

            os.chmod(temp_file, 0o600)
            temp_file.replace(self._config_path)
        except Exception as exc:
            if temp_file.exists():
                temp_file.unlink(missing_ok=True)
            logger.error("Failed to write device config to %s: %s", self._config_path, exc)
            raise


__all__ = ["DEFAULT_CONFIG_PATH", "DeviceConfigManager", "RemoteDevice"]
