"""Common models returned by the ServiceDeck API client."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class HealthInfo:
    """Backend health check summary and systemd D-Bus connection statuses."""

    status: str
    systemd_connected: bool
    systemd_user_connected: bool
    systemd_system_connected: bool
    active_scope: str
    version: str
    listen_address: str = "127.0.0.1:8000"
    allow_interactive_authorization: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "HealthInfo":
        """Construct HealthInfo from an API JSON response dict."""
        return cls(
            status=data.get("status", "unknown"),
            systemd_connected=bool(data.get("systemd_connected", False)),
            systemd_user_connected=bool(data.get("systemd_user_connected", False)),
            systemd_system_connected=bool(data.get("systemd_system_connected", False)),
            active_scope=data.get("active_scope", "user"),
            version=data.get("version", ""),
            listen_address=data.get("listen_address", "127.0.0.1:8000"),
            allow_interactive_authorization=bool(data.get("allow_interactive_authorization", True)),
        )


@dataclass(frozen=True, slots=True)
class ScopeInfo:
    """Active and available service scopes."""

    active_scope: str
    available_scopes: list[str] = field(default_factory=lambda: ["user", "system"])

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScopeInfo":
        """Construct ScopeInfo from an API JSON response dict."""
        return cls(
            active_scope=data.get("active_scope", "user"),
            available_scopes=list(data.get("available_scopes", ["user", "system"])),
        )
