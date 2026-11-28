"""Service domain models returned by the ServiceDeck API client."""

import signal
import time
from dataclasses import dataclass
from typing import Any, Literal


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
class ServiceEvent:
    """One live change from ``watch_services``.

    ``kind`` is ``ready`` (watching; list services now to start from a fresh state),
    ``changed`` (``service`` holds the new state), ``removed`` (``name`` is gone) or
    ``resync`` (bulk change: list services again).
    """

    kind: Literal["ready", "changed", "removed", "resync"]
    scope: str = "user"
    name: str | None = None
    service: Service | None = None

    @classmethod
    def from_sse(cls, event: str, data: Any) -> "ServiceEvent | None":
        """Build from a Server-Sent Event, or return None for an unknown event type."""
        payload = data if isinstance(data, dict) else {}
        if event == "service":
            service = Service.from_dict(payload)
            return cls(kind="changed", scope=service.scope, name=service.name, service=service)
        if event == "removed":
            return cls(kind="removed", scope=payload.get("scope", "user"), name=payload.get("name"))
        if event in ("ready", "resync"):
            return cls(kind=event, scope=payload.get("scope", "user"))  # type: ignore[arg-type]
        return None


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
class DropInFile:
    """A drop-in file applied on top of a unit's main file."""

    path: str
    content: str
    #: True when ServiceDeck can edit or remove it (it is in the scope's writable directory).
    editable: bool = False

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DropInFile":
        return cls(
            path=data.get("path", ""),
            content=data.get("content", ""),
            editable=bool(data.get("editable", False)),
        )


@dataclass(frozen=True, slots=True)
class ServiceUnitFile:
    """Represents a service unit file on disk, plus the drop-ins applied to it."""

    service: str
    fragment_path: str | None
    content: str
    scope: str = "user"
    drop_ins: tuple[DropInFile, ...] = ()
    override_path: str | None = None
    need_daemon_reload: bool = False

    @property
    def editable_drop_ins(self) -> tuple[DropInFile, ...]:
        return tuple(d for d in self.drop_ins if d.editable)

    @property
    def override_content(self) -> str | None:
        """Content of ``override_path`` if that drop-in exists."""
        for drop_in in self.drop_ins:
            if drop_in.path == self.override_path:
                return drop_in.content
        return None

    def effective_text(self) -> str:
        """The fragment followed by each drop-in, the way ``systemctl cat`` prints them."""
        parts = [f"# {self.fragment_path or '(no unit file on disk)'}\n{self.content.rstrip()}"]
        parts += [f"# {d.path}\n{d.content.rstrip()}" for d in self.drop_ins]
        return "\n\n".join(parts) + "\n"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ServiceUnitFile":
        """Construct ServiceUnitFile from API JSON response dict."""
        return cls(
            service=data.get("service", ""),
            fragment_path=data.get("fragment_path"),
            content=data.get("content", ""),
            scope=data.get("scope", "user"),
            drop_ins=tuple(DropInFile.from_dict(d) for d in data.get("drop_ins") or []),
            override_path=data.get("override_path"),
            need_daemon_reload=bool(data.get("need_daemon_reload", False)),
        )


@dataclass(frozen=True, slots=True)
class OverrideResult:
    """Result of writing (or, for comment-only content, removing) a drop-in override."""

    service: str
    scope: str
    path: str
    removed: bool = False
    load_state: str = "unknown"
    warnings: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "OverrideResult":
        return cls(
            service=data.get("service", ""),
            scope=data.get("scope", "user"),
            path=data.get("path", ""),
            removed=bool(data.get("removed", False)),
            load_state=data.get("load_state", "unknown"),
            warnings=tuple(data.get("warnings") or ()),
        )


@dataclass(frozen=True, slots=True)
class RevertResult:
    """Result of reverting a unit to its vendor configuration."""

    service: str
    scope: str
    removed_paths: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RevertResult":
        return cls(
            service=data.get("service", ""),
            scope=data.get("scope", "user"),
            removed_paths=tuple(data.get("removed_paths") or ()),
        )


#: Exit status names, as ``systemctl status`` prints them (systemd.exec(5), "Process Exit Codes").
EXIT_STATUS_NAMES: dict[int, str] = {
    0: "SUCCESS",
    1: "FAILURE",
    2: "INVALIDARGUMENT",
    3: "NOTIMPLEMENTED",
    4: "NOPERMISSION",
    5: "NOTINSTALLED",
    6: "NOTCONFIGURED",
    7: "NOTRUNNING",
    200: "CHDIR",
    201: "NICE",
    202: "FDS",
    203: "EXEC",
    204: "MEMORY",
    205: "LIMITS",
    208: "STDIN",
    209: "STDOUT",
    210: "CHROOT",
    216: "GROUP",
    217: "USER",
    226: "NAMESPACE",
}

#: ``ExecMainCode`` values (``CLD_*`` from waitid(2)).
_EXIT_CODES = {1: "exited", 2: "killed", 3: "dumped"}


def describe_exit(code: int | None, status: int | None) -> str | None:
    """``systemctl status`` style text for the main process's last exit, e.g.
    ``exited, status=203/EXEC`` or ``killed, signal=SEGV``. None if it has not exited."""
    kind = _EXIT_CODES.get(code or 0)
    if kind is None or status is None:
        return None
    if kind == "exited":
        name = EXIT_STATUS_NAMES.get(status)
        return f"exited, status={status}/{name}" if name else f"exited, status={status}"
    try:
        signal_name = signal.Signals(status).name.removeprefix("SIG")
    except ValueError:
        signal_name = str(status)
    return f"{kind}, signal={signal_name}"


def format_ago(seconds: float) -> str:
    """Compact age such as ``42s``, ``5m``, ``3h 12m`` or ``2d 4h``."""
    total = max(0, int(seconds))
    days, rest = divmod(total, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    if minutes:
        return f"{minutes}m"
    return f"{secs}s"


@dataclass(frozen=True, slots=True)
class ServiceResources:
    """Runtime resource consumption metrics and health of a service."""

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
    #: Automatic restarts by systemd (``NRestarts``); None on very old systemd.
    n_restarts: int | None = None
    #: Outcome of the last run: success, exit-code, signal, core-dump, timeout, ...
    result: str | None = None
    exec_main_code: int | None = None
    exec_main_status: int | None = None
    exec_main_exit_timestamp: int | None = None
    #: Microseconds since epoch of the last ActiveState change.
    state_change_timestamp: int | None = None

    @property
    def is_failed(self) -> bool:
        return self.active_state == "failed"

    @property
    def last_exit(self) -> str | None:
        """How the main process last ended, ``systemctl status`` style."""
        return describe_exit(self.exec_main_code, self.exec_main_status)

    def failed_for_seconds(self, now: float | None = None) -> float | None:
        """Seconds since the unit failed, or None if it is not failed."""
        if not self.is_failed or not self.state_change_timestamp:
            return None
        current = time.time() if now is None else now
        return max(0.0, current - self.state_change_timestamp / 1_000_000)

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
            n_restarts=data.get("n_restarts"),
            result=data.get("result"),
            exec_main_code=data.get("exec_main_code"),
            exec_main_status=data.get("exec_main_status"),
            exec_main_exit_timestamp=data.get("exec_main_exit_timestamp"),
            state_change_timestamp=data.get("state_change_timestamp"),
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
