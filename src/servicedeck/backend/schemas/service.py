"""Pydantic schemas for API request and response serialization."""

from pydantic import BaseModel, ConfigDict, Field

from servicedeck.backend.models.service import Service, ServiceScope


class ScopeResponse(BaseModel):
    """Response schema representing the active and available service scopes."""

    model_config = ConfigDict(frozen=True)

    active_scope: str = Field(description="Currently active scope ('user' or 'system')")
    available_scopes: list[str] = Field(
        default=["user", "system"],
        description="Supported scopes",
    )


class ScopeUpdateRequest(BaseModel):
    """Request schema for toggling the active service scope."""

    model_config = ConfigDict(frozen=True)

    scope: ServiceScope = Field(description="Target scope to activate ('user' or 'system')")


class HealthResponse(BaseModel):
    """Response schema for backend and systemd health checks."""

    model_config = ConfigDict(frozen=True)

    status: str = Field(default="ok", description="Health status (ok, degraded, down)")
    systemd_connected: bool = Field(description="Whether at least one systemd connection is active")
    systemd_user_connected: bool = Field(description="Whether user systemd D-Bus is connected")
    systemd_system_connected: bool = Field(description="Whether system systemd D-Bus is connected")
    active_scope: str = Field(default="user", description="Currently active service scope")
    version: str = Field(description="ServiceDeck backend version")
    listen_address: str = Field(
        default="127.0.0.1:8000",
        description="Bind address and port of the backend server",
    )
    allow_interactive_authorization: bool = Field(
        default=True,
        description="Whether interactive Polkit authorization is permitted on D-Bus calls",
    )


class ServiceResponse(BaseModel):
    """Response schema representing a single system service."""

    model_config = ConfigDict(frozen=True, from_attributes=True)

    name: str = Field(description="Primary systemd unit name (e.g. ssh.service)")
    description: str = Field(description="Human-readable description of the service")
    load_state: str = Field(description="Load state (e.g. loaded, not-found, masked)")
    active_state: str = Field(
        description="High-level activation state (e.g. active, inactive, failed)"
    )
    sub_state: str = Field(description="Low-level sub-state (e.g. running, dead, exited)")
    unit_file_state: str = Field(
        description="Unit file configuration state (e.g. enabled, disabled, static)"
    )
    scope: str = Field(default="user", description="Service scope ('user' or 'system')")

    @classmethod
    def from_domain(cls, service: Service) -> "ServiceResponse":
        """Convert an internal domain Service model to an API response schema."""
        return cls(
            name=service.name,
            description=service.description,
            load_state=service.load_state,
            active_state=service.active_state,
            sub_state=service.sub_state,
            unit_file_state=service.unit_file_state,
            scope=service.scope,
        )


class ServiceOperationResponse(BaseModel):
    """Response schema for lifecycle operations (start, stop, restart, etc.)."""

    model_config = ConfigDict(frozen=True)

    success: bool = Field(description="Whether the requested operation succeeded")
    service: str = Field(description="Name of the service that the operation was applied to")
    operation: str = Field(description="Operation that was executed")
    scope: str = Field(default="user", description="Service scope applied to the operation")
    message: str | None = Field(default=None, description="Additional context or outcome message")


class ErrorDetail(BaseModel):
    """Standardized API error response payload."""

    model_config = ConfigDict(frozen=True)

    error: str = Field(description="Machine-readable error type/code")
    message: str = Field(description="Human-readable error explanation")
    details: dict = Field(default_factory=dict, description="Additional diagnostic context")


class UnitFileResponse(BaseModel):
    """Response schema representing a service unit file on disk."""

    model_config = ConfigDict(frozen=True)

    service: str = Field(description="Service unit name")
    fragment_path: str | None = Field(description="On-disk path of the unit file")
    content: str = Field(description="Contents of the unit file")
    scope: str = Field(default="user", description="Service scope")


class ResourceUsageResponse(BaseModel):
    """Response schema representing runtime resource metrics for a service."""

    model_config = ConfigDict(frozen=True)

    service: str = Field(description="Service unit name")
    cpu_usage_nsec: int | None = Field(
        default=None, description="Total CPU time consumed in nanoseconds"
    )
    memory_current_bytes: int | None = Field(
        default=None, description="Current memory consumption in bytes"
    )
    disk_read_bytes: int | None = Field(default=None, description="Cumulative disk read bytes")
    disk_write_bytes: int | None = Field(default=None, description="Cumulative disk write bytes")
    tasks_current: int | None = Field(default=None, description="Current number of tasks/threads")
    main_pid: int | None = Field(default=None, description="Main PID of the service process")
    active_enter_timestamp: int | None = Field(
        default=None, description="Microseconds since epoch when service became active"
    )
    active_state: str = Field(default="inactive", description="Service active state")
    scope: str = Field(default="user", description="Service scope")


class ServiceLogsResponse(BaseModel):
    """Response schema containing journal log entries for a service."""

    model_config = ConfigDict(frozen=True)

    service: str = Field(description="Service unit name")
    logs: str = Field(description="Recent journal log text")
    scope: str = Field(default="user", description="Service scope")
    lines: int = Field(default=200, description="Requested number of lines")


class CreateServiceRequest(BaseModel):
    """Request schema for creating a new custom systemd service unit."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(description="Service unit name (e.g. my-app.service)")
    content: str = Field(description="Complete systemd unit file content")
    scope: ServiceScope | None = Field(
        default=None, description="Target scope ('user' or 'system')"
    )
    overwrite: bool = Field(default=False, description="Whether to overwrite existing unit file")


class CreateServiceResponse(BaseModel):
    """Response schema after successfully creating a custom service unit."""

    model_config = ConfigDict(frozen=True)

    success: bool = Field(default=True, description="Whether the service was created successfully")
    service: str = Field(description="Created service unit name")
    path: str = Field(description="Filesystem path where unit file was written")
    scope: str = Field(description="Service scope where unit was installed")


class DaemonReloadResponse(BaseModel):
    """Response schema for systemd daemon-reload operation."""

    model_config = ConfigDict(frozen=True)

    success: bool = Field(default=True, description="Whether daemon-reload succeeded")
    scope: str = Field(description="Scope in which daemon-reload was executed")
    message: str = Field(default="systemd daemon reloaded successfully")
