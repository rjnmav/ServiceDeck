"""Service domain models returned by the ServiceDeck API client."""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Service:
    """Represents a systemd service unit."""

    name: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    unit_file_state: str
    scope: str = "user"

    @property
    def is_active(self) -> bool:
        """Return True if active_state is 'active'."""
        return self.active_state == "active"

    @property
    def is_running(self) -> bool:
        """Return True if sub_state is 'running'."""
        return self.sub_state == "running"

    @property
    def is_failed(self) -> bool:
        """Return True if active_state or sub_state is 'failed'."""
        return self.active_state == "failed" or self.sub_state == "failed"

    @property
    def is_enabled(self) -> bool:
        """Return True if unit_file_state is 'enabled'."""
        return self.unit_file_state == "enabled"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Service":
        """Construct Service from an API JSON response dict."""
        return cls(
            name=data["name"],
            description=data.get("description", ""),
            load_state=data.get("load_state", "unknown"),
            active_state=data.get("active_state", "unknown"),
            sub_state=data.get("sub_state", "unknown"),
            unit_file_state=data.get("unit_file_state", "unknown"),
            scope=data.get("scope", "user"),
        )


@dataclass(frozen=True, slots=True)
class ServiceOperationResult:
    """Outcome of a service lifecycle operation (start, stop, restart, etc.)."""

    success: bool
    service: str
    operation: str
    scope: str = "user"
    message: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceOperationResult":
        """Construct ServiceOperationResult from an API JSON response dict."""
        return cls(
            success=bool(data.get("success", False)),
            service=data.get("service", ""),
            operation=data.get("operation", ""),
            scope=data.get("scope", "user"),
            message=data.get("message"),
        )


@dataclass(frozen=True, slots=True)
class ServiceUnitFile:
    """Represents a service unit file on disk."""

    service: str
    fragment_path: str | None
    content: str
    scope: str = "user"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceUnitFile":
        """Construct ServiceUnitFile from API JSON response dict."""
        return cls(
            service=data.get("service", ""),
            fragment_path=data.get("fragment_path"),
            content=data.get("content", ""),
            scope=data.get("scope", "user"),
        )


@dataclass(frozen=True, slots=True)
class ServiceResources:
    """Runtime resource consumption metrics for a service."""

    service: str
    cpu_usage_nsec: int | None = None
    memory_current_bytes: int | None = None
    disk_read_bytes: int | None = None
    disk_write_bytes: int | None = None
    tasks_current: int | None = None
    main_pid: int | None = None
    active_enter_timestamp: int | None = None
    active_state: str = "inactive"
    scope: str = "user"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceResources":
        """Construct ServiceResources from API JSON response dict."""
        return cls(
            service=data.get("service", ""),
            cpu_usage_nsec=data.get("cpu_usage_nsec"),
            memory_current_bytes=data.get("memory_current_bytes"),
            disk_read_bytes=data.get("disk_read_bytes"),
            disk_write_bytes=data.get("disk_write_bytes"),
            tasks_current=data.get("tasks_current"),
            main_pid=data.get("main_pid"),
            active_enter_timestamp=data.get("active_enter_timestamp"),
            active_state=data.get("active_state", "inactive"),
            scope=data.get("scope", "user"),
        )


@dataclass(frozen=True, slots=True)
class ServiceLogs:
    """Journal log entries for a service."""

    service: str
    logs: str
    scope: str = "user"
    lines: int = 200

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceLogs":
        """Construct ServiceLogs from API JSON response dict."""
        return cls(
            service=data.get("service", ""),
            logs=data.get("logs", ""),
            scope=data.get("scope", "user"),
            lines=data.get("lines", 200),
        )


@dataclass(frozen=True, slots=True)
class CreatedService:
    """Result of creating a new custom systemd service."""

    success: bool
    service: str
    path: str
    scope: str = "user"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CreatedService":
        """Construct CreatedService from API JSON response dict."""
        return cls(
            success=bool(data.get("success", False)),
            service=data.get("service", ""),
            path=data.get("path", ""),
            scope=data.get("scope", "user"),
        )


@dataclass(frozen=True, slots=True)
class DaemonReloadResult:
    """Result of reloading systemd daemon."""

    success: bool
    scope: str = "user"
    message: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DaemonReloadResult":
        """Construct DaemonReloadResult from API JSON response dict."""
        return cls(
            success=bool(data.get("success", False)),
            scope=data.get("scope", "user"),
            message=data.get("message", ""),
        )
