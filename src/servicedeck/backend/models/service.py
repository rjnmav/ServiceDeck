"""Domain models representing Linux systemd services."""

import re
from dataclasses import dataclass
from typing import Literal

SERVICE_NAME_REGEX = re.compile(r"^[a-zA-Z0-9@_\.\-]+$")

ServiceScope = Literal["user", "system"]
VALID_SCOPES: tuple[str, ...] = ("user", "system")


def validate_scope(scope: str) -> str:
    """Validate that scope is either 'user' or 'system'."""
    normalized = scope.strip().lower()
    if normalized not in VALID_SCOPES:
        from servicedeck.backend.exceptions import ServiceDeckError

        raise ServiceDeckError(
            f"Invalid scope '{scope}'. Must be 'user' or 'system'.",
            details={"scope": scope, "valid_scopes": list(VALID_SCOPES)},
        )
    return normalized


def normalize_service_name(name: str) -> str:
    """Normalize a service name by stripping whitespace and ensuring .service suffix."""
    cleaned = name.strip()
    if not cleaned:
        from servicedeck.backend.exceptions import InvalidServiceNameError

        raise InvalidServiceNameError(name, "Service name cannot be empty")

    if not SERVICE_NAME_REGEX.match(cleaned):
        from servicedeck.backend.exceptions import InvalidServiceNameError

        raise InvalidServiceNameError(cleaned, "Service name contains invalid characters")

    if not cleaned.endswith(".service"):
        cleaned = f"{cleaned}.service"

    return cleaned


@dataclass(frozen=True, slots=True)
class Service:
    """Internal domain representation of a systemd service unit.

    Systemd states are treated as external strings because systemd supports
    dynamic and varied states across different units and versions.
    """

    name: str
    description: str
    load_state: str
    active_state: str
    sub_state: str
    unit_file_state: str
    scope: str = "user"

    @property
    def is_active(self) -> bool:
        """Return True if the service active_state is 'active'."""
        return self.active_state == "active"

    @property
    def is_running(self) -> bool:
        """Return True if the service sub_state is 'running'."""
        return self.sub_state == "running"

    @property
    def is_failed(self) -> bool:
        """Return True if either active_state or sub_state is 'failed'."""
        return self.active_state == "failed" or self.sub_state == "failed"

    @property
    def is_enabled(self) -> bool:
        """Return True if unit_file_state is 'enabled'."""
        return self.unit_file_state == "enabled"


@dataclass(frozen=True, slots=True)
class ServiceResourceUsage:
    """Resource consumption metrics for an active systemd service unit."""

    service: str
    scope: str
    is_active: bool
    cpu_usage_nsec: int | None = None
    memory_current: int | None = None
    io_read_bytes: int | None = None
    io_write_bytes: int | None = None
    tasks_current: int | None = None
    process_count: int | None = None
    active_enter_timestamp_usec: int | None = None
    main_pid: int | None = None
