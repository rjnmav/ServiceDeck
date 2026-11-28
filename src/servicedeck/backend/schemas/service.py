"""Pydantic schemas for API request and response serialization."""

from pydantic import BaseModel, ConfigDict, Field

from servicedeck.backend.models.service import Service, ServiceResourceUsage, ServiceScope
from servicedeck.backend.models.unit_files import DEFAULT_DROP_IN, OverrideResult, UnitFileInfo


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


class DropInSchema(BaseModel):
    """One drop-in file applied on top of a unit's main file."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(description="On-disk path of the drop-in")
    content: str = Field(description="Contents of the drop-in")
    editable: bool = Field(
        default=False, description="Whether the drop-in is in ServiceDeck's writable directory"
    )


class UnitFileResponse(BaseModel):
    """Response schema representing a service unit file on disk, plus its drop-ins."""

    model_config = ConfigDict(frozen=True)

    service: str = Field(description="Service unit name")
    fragment_path: str | None = Field(description="On-disk path of the unit file")
    content: str = Field(description="Contents of the unit file")
    scope: str = Field(default="user", description="Service scope")
    drop_ins: list[DropInSchema] = Field(
        default_factory=list, description="Drop-ins applied in order (systemctl cat)"
    )
    override_path: str | None = Field(
        default=None, description="Where 'Edit override' writes (<unit>.d/override.conf)"
    )
    need_daemon_reload: bool = Field(
        default=False, description="Whether files changed on disk since the last daemon-reload"
    )

    @classmethod
    def from_domain(cls, info: UnitFileInfo) -> "UnitFileResponse":
        return cls(
            service=info.service,
            fragment_path=info.fragment_path,
            content=info.content,
            scope=info.scope,
            drop_ins=[
                DropInSchema(path=d.path, content=d.content, editable=d.editable)
                for d in info.drop_ins
            ],
            override_path=info.override_path,
            need_daemon_reload=info.need_daemon_reload,
        )


class WriteOverrideRequest(BaseModel):
    """Request schema for writing a drop-in override (systemctl edit)."""

    model_config = ConfigDict(frozen=True)

    content: str = Field(
        description="Drop-in content. Only comments/whitespace removes the drop-in instead."
    )
    drop_in: str = Field(default=DEFAULT_DROP_IN, description="Drop-in file name (*.conf)")


class OverrideResponse(BaseModel):
    """Response schema after writing (or removing) a drop-in override."""

    model_config = ConfigDict(frozen=True)

    success: bool = Field(default=True)
    service: str = Field(description="Service unit name")
    scope: str = Field(description="Service scope")
    path: str = Field(description="Path of the drop-in that was written or removed")
    removed: bool = Field(default=False, description="True if empty content removed the drop-in")
    load_state: str = Field(default="unknown", description="Unit LoadState after reload")
    warnings: list[str] = Field(default_factory=list, description="Non-fatal syntax warnings")

    @classmethod
    def from_domain(cls, result: OverrideResult) -> "OverrideResponse":
        return cls(
            service=result.service,
            scope=result.scope,
            path=result.path,
            removed=result.removed,
            load_state=result.load_state,
            warnings=list(result.warnings),
        )


class RevertOverridesResponse(BaseModel):
    """Response schema after reverting a unit to its vendor configuration."""

    model_config = ConfigDict(frozen=True)

    success: bool = Field(default=True)
    service: str = Field(description="Service unit name")
    scope: str = Field(description="Service scope")
    removed_paths: list[str] = Field(default_factory=list, description="Drop-ins deleted")


class ElevationStatusResponse(BaseModel):
    """Whether system unit file changes on this computer currently run as root."""

    model_config = ConfigDict(frozen=True)

    elevated: bool = Field(description="True while the local administrator session is active")
    idle_timeout: float = Field(
        default=0, description="Seconds of inactivity before the session is dropped"
    )


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
    n_restarts: int | None = Field(
        default=None, description="Automatic restarts by systemd (NRestarts)"
    )
    result: str | None = Field(
        default=None, description="Outcome of the last run (success, exit-code, signal, ...)"
    )
    exec_main_code: int | None = Field(
        default=None, description="How the main process ended: 1 exited, 2 killed, 3 dumped"
    )
    exec_main_status: int | None = Field(
        default=None, description="Exit status, or signal number when killed"
    )
    exec_main_exit_timestamp: int | None = Field(
        default=None, description="Microseconds since epoch when the main process ended"
    )
    state_change_timestamp: int | None = Field(
        default=None, description="Microseconds since epoch of the last ActiveState change"
    )

    @classmethod
    def from_domain(cls, usage: ServiceResourceUsage) -> "ResourceUsageResponse":
        known = usage.active_state and usage.active_state != "unknown"
        return cls(
            service=usage.service,
            cpu_usage_nsec=usage.cpu_usage_nsec,
            memory_current_bytes=usage.memory_current,
            disk_read_bytes=usage.io_read_bytes,
            disk_write_bytes=usage.io_write_bytes,
            tasks_current=usage.tasks_current,
            main_pid=usage.main_pid,
            active_enter_timestamp=usage.active_enter_timestamp_usec,
            active_state=usage.active_state
            if known
            else ("active" if usage.is_active else "inactive"),
            scope=usage.scope,
            n_restarts=usage.n_restarts,
            result=usage.result,
            exec_main_code=usage.exec_main_code,
            exec_main_status=usage.exec_main_status,
            exec_main_exit_timestamp=usage.exec_main_exit_timestamp_usec,
            state_change_timestamp=usage.state_change_timestamp_usec,
        )


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
