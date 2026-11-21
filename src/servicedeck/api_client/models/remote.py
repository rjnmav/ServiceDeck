"""Remote device domain models returned by the ServiceDeck API client."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class RemoteDevice:
    """Represents a configured remote Linux machine."""

    id: str
    display_name: str
    hostname: str
    port: int = 22
    username: str | None = None
    ssh_key_path: str | None = None
    agent_mode: str = "bundled"
    connected: bool = False

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteDevice":
        """Construct RemoteDevice from API response dict."""
        return cls(
            id=str(data["id"]),
            display_name=str(data.get("display_name", data["id"])),
            hostname=str(data["hostname"]),
            port=int(data.get("port", 22)),
            username=str(data["username"]) if data.get("username") else None,
            ssh_key_path=str(data["ssh_key_path"]) if data.get("ssh_key_path") else None,
            agent_mode=str(data.get("agent_mode") or "bundled"),
            connected=bool(data.get("connected", False)),
        )


@dataclass(frozen=True, slots=True)
class RemoteConnectionInfo:
    """Represents the live connection state and agent handshake metadata."""

    device_id: str
    connected: bool
    remote_host: str | None = None
    remote_user: str | None = None
    remote_uid: int | None = None
    remote_version: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RemoteConnectionInfo":
        """Construct RemoteConnectionInfo from API response dict."""
        return cls(
            device_id=str(data["device_id"]),
            connected=bool(data.get("connected", False)),
            remote_host=str(data["remote_host"]) if data.get("remote_host") else None,
            remote_user=str(data["remote_user"]) if data.get("remote_user") else None,
            remote_uid=int(data["remote_uid"]) if data.get("remote_uid") is not None else None,
            remote_version=str(data["remote_version"]) if data.get("remote_version") else None,
        )


@dataclass(frozen=True, slots=True)
class HostKeyInfo:
    """SSH host key presented by a remote device and its trust status."""

    hostname: str
    port: int
    status: str  # "trusted" | "unknown" | "changed"
    key_type: str
    fingerprint: str

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HostKeyInfo":
        """Construct HostKeyInfo from an API response (or error details) dict."""
        return cls(
            hostname=str(data.get("hostname", "")),
            port=int(data.get("port", 22)),
            status=str(data.get("status", "unknown")),
            key_type=str(data.get("key_type", "")),
            fingerprint=str(data.get("fingerprint", "")),
        )


@dataclass(frozen=True, slots=True)
class KeySetupInfo:
    """Result of installing the SSH login key on a remote device."""

    device: RemoteDevice
    key_path: str
    key_fingerprint: str
    added: bool

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "KeySetupInfo":
        """Construct KeySetupInfo from API response dict."""
        return cls(
            device=RemoteDevice.from_dict(data["device"]),
            key_path=str(data["key_path"]),
            key_fingerprint=str(data["key_fingerprint"]),
            added=bool(data.get("added", True)),
        )


__all__ = ["HostKeyInfo", "KeySetupInfo", "RemoteConnectionInfo", "RemoteDevice"]
