"""systemd adapter communicating via D-Bus for both User and System scopes."""

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any, Protocol

from dbus_fast.constants import MessageFlag, MessageType
from dbus_fast.message import Message

from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    PermissionDeniedError,
    PolkitAgentUnavailableError,
    ServiceNotFoundError,
    ServiceOperationError,
    SystemdConnectionError,
)
from servicedeck.backend.infrastructure.dbus.config import DbusSettingsLike
from servicedeck.backend.infrastructure.dbus.connection import DbusConnectionManager
from servicedeck.backend.models.service import (
    Service,
    ServiceEvent,
    ServiceResourceUsage,
    normalize_service_name,
    validate_scope,
)

logger = logging.getLogger(__name__)

UNIT_PATH_PREFIX = "/org/freedesktop/systemd1/unit/"
_UNIT_PATH_ESCAPE = re.compile(r"_([0-9a-fA-F]{2})")


def unit_name_from_path(path: str) -> str | None:
    """Decode a systemd unit object path (``.../unit/nginx_2eservice``) to its unit name."""
    if not path.startswith(UNIT_PATH_PREFIX):
        return None
    encoded = path[len(UNIT_PATH_PREFIX) :]
    if not encoded or "/" in encoded:
        return None
    return _UNIT_PATH_ESCAPE.sub(lambda m: chr(int(m.group(1), 16)), encoded)


class SystemdAdapter(Protocol):
    """Protocol defining the interface for interacting with systemd."""

    async def list_services(self, scope: str = "user") -> list[Service]:
        """List all discovered systemd services for the specified scope."""
        ...

    async def get_service(self, name: str, scope: str = "user") -> Service:
        """Get details for a single service by name within the specified scope."""
        ...

    async def start_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Start a systemd service."""
        ...

    async def stop_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Stop a systemd service."""
        ...

    async def restart_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Restart a systemd service."""
        ...

    async def reload_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Reload a systemd service configuration."""
        ...

    async def enable_service(self, name: str, scope: str = "user") -> None:
        """Enable a systemd service to start on boot/login."""
        ...

    async def disable_service(self, name: str, scope: str = "user") -> None:
        """Disable a systemd service from starting on boot/login."""
        ...

    async def mask_service(self, name: str, scope: str = "user") -> None:
        """Mask a systemd service, preventing it from starting."""
        ...

    async def unmask_service(self, name: str, scope: str = "user") -> None:
        """Unmask a systemd service."""
        ...

    async def reload_daemon(self, scope: str = "user") -> None:
        """Reload systemd manager configuration (daemon-reload)."""
        ...

    async def get_unit_file(self, name: str, scope: str = "user") -> tuple[str | None, str]:
        """Retrieve the on-disk unit file fragment path and content."""
        ...

    async def get_service_resources(self, name: str, scope: str = "user") -> ServiceResourceUsage:
        """Retrieve runtime resource metrics for an active service."""
        ...

    async def get_service_logs(self, name: str, lines: int = 200, scope: str = "user") -> str:
        """Retrieve recent journal log entries for a service unit."""
        ...

    async def create_service(
        self, name: str, content: str, scope: str = "user", overwrite: bool = False
    ) -> str:
        """Create and install a new systemd unit file and reload daemon."""
        ...

    async def is_healthy(self, scope: str = "user") -> bool:
        """Check if systemd D-Bus interface is accessible for the specified scope."""
        ...

    def watch_services(self, scope: str = "user") -> AsyncIterator[ServiceEvent]:
        """Yield live service changes; the first event is always ``ready``."""
        ...

    def follow_service_logs(
        self, name: str, lines: int = 200, scope: str = "user"
    ) -> AsyncIterator[str]:
        """Yield the last ``lines`` journal lines, then new ones as they are written.

        The first item is always ``""`` (a readiness marker, not a log line).
        """
        ...


class DbusSystemdAdapter:
    """Production implementation of SystemdAdapter using dbus-fast for User and System buses."""

    SYSTEMD_BUS_NAME = "org.freedesktop.systemd1"
    SYSTEMD_OBJECT_PATH = "/org/freedesktop/systemd1"
    MANAGER_INTERFACE = "org.freedesktop.systemd1.Manager"
    PROPERTIES_INTERFACE = "org.freedesktop.DBus.Properties"
    UNIT_INTERFACE = "org.freedesktop.systemd1.Unit"
    SERVICE_INTERFACE = "org.freedesktop.systemd1.Service"
    UNAVAILABLE_COUNTER = 18446744073709551615
    DBUS_BUS_NAME = "org.freedesktop.DBus"
    DBUS_OBJECT_PATH = "/org/freedesktop/DBus"

    #: Coalesce bursts of signals (a restart emits several) into one update per unit.
    WATCH_DEBOUNCE_SECONDS = 0.15
    #: How often an idle watcher checks that its bus is still connected.
    WATCH_LIVENESS_SECONDS = 5.0
    WATCH_MATCH_RULES: tuple[str, ...] = (
        "type='signal',sender='org.freedesktop.systemd1',"
        "interface='org.freedesktop.DBus.Properties',member='PropertiesChanged',"
        "arg0='org.freedesktop.systemd1.Unit'",
        "type='signal',sender='org.freedesktop.systemd1',"
        "interface='org.freedesktop.systemd1.Manager',path='/org/freedesktop/systemd1'",
    )

    def __init__(
        self,
        connection_manager: DbusConnectionManager | None = None,
        settings: DbusSettingsLike | None = None,
    ) -> None:
        if settings is None:
            # Imported lazily: see DbusConnectionManager.__init__.
            from servicedeck.backend.config.settings import get_settings

            settings = get_settings()
        self._settings: DbusSettingsLike = settings
        self._connection_manager = connection_manager or DbusConnectionManager(self._settings)
        # Live watchers per bus; systemd only emits unit signals while someone is subscribed.
        self._subscribers: dict[Any, int] = {}

    def _get_variant_value(self, variant: object) -> str:
        """Helper to extract unwrapped value from a D-Bus Variant or object."""
        if hasattr(variant, "value"):
            val = variant.value
        else:
            val = variant
        return str(val) if val is not None else ""

    def _handle_error_reply(
        self, reply: Message, operation: str, service_name: str, scope: str = "user"
    ) -> None:
        """Translate a D-Bus error reply Message into an appropriate domain exception."""
        error_name = reply.error_name or "UnknownError"
        error_text = reply.body[0] if reply.body and len(reply.body) > 0 else error_name

        logger.warning(
            "[%s] D-Bus error for %s on %s: %s - %s",
            scope,
            operation,
            service_name,
            error_name,
            error_text,
        )

        if "InteractiveAuthorizationRequired" in error_name:
            msg = (
                f"Interactive authorization required for {operation} on '{service_name}' ({scope} scope). "
                "No Polkit authentication agent is available in this session, or interactive authorization is disabled. "
                "In a desktop environment, ensure a Polkit agent is running; in a headless/TUI session, verify system authorization policy."
            )
            if error_text and error_text != error_name:
                msg += f" Details: {error_text}"
            raise PolkitAgentUnavailableError(
                action=operation,
                service_name=service_name,
                scope=scope,
                message=msg,
            )

        if "AccessDenied" in error_name or "AuthorizationFailed" in error_name:
            raise AuthorizationDeniedError(
                action=operation,
                service_name=service_name,
                reason=str(error_text),
            )

        if "NoSuchUnit" in error_name or "UnknownObject" in error_name:
            raise ServiceNotFoundError(service_name=service_name, message=str(error_text))

        raise ServiceOperationError(
            service_name=service_name,
            operation=operation,
            reason=str(error_text),
        )

    def _get_message_flags(self, scope: str) -> MessageFlag:
        """Return message flags based on configuration.

        When allow_interactive_authorization is True, D-Bus calls include
        ALLOW_INTERACTIVE_AUTHORIZATION, enabling Polkit desktop agents
        to prompt the user for credentials when needed.
        """
        if self._settings.allow_interactive_authorization:
            return MessageFlag.ALLOW_INTERACTIVE_AUTHORIZATION
        return MessageFlag.NONE

    async def is_healthy(self, scope: str = "user") -> bool:
        """Check whether systemd Manager is reachable via D-Bus for the specified scope."""
        valid_scope = validate_scope(scope)
        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.PROPERTIES_INTERFACE,
                    member="Get",
                    signature="ss",
                    body=[self.MANAGER_INTERFACE, "Version"],
                )
            )
            return reply.message_type == MessageType.METHOD_RETURN
        except Exception as exc:
            logger.debug("[%s] Health check failed: %s", valid_scope, exc)
            return False

    async def list_services(self, scope: str = "user") -> list[Service]:
        """Discover systemd services by combining loaded units and installed unit files for scope."""
        valid_scope = validate_scope(scope)
        try:
            bus = await self._connection_manager.get_bus(valid_scope)

            # Query currently loaded units
            units_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="ListUnits",
                )
            )
            if units_reply.message_type == MessageType.ERROR:
                self._handle_error_reply(units_reply, "list_services", "all", valid_scope)

            # Query installed unit files to determine enable/disable states
            files_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="ListUnitFiles",
                )
            )

            unit_file_states: dict[str, str] = {}
            if files_reply.message_type == MessageType.METHOD_RETURN and files_reply.body:
                for file_path, file_state in files_reply.body[0]:
                    if isinstance(file_path, str) and file_path.endswith(".service"):
                        unit_file_states[os.path.basename(file_path)] = str(file_state)

            discovered: dict[str, Service] = {}

            # Process loaded units
            if units_reply.body and len(units_reply.body) > 0:
                for unit_data in units_reply.body[0]:
                    name = str(unit_data[0])
                    if not name.endswith(".service"):
                        continue

                    description = str(unit_data[1]) if len(unit_data) > 1 else ""
                    load_state = str(unit_data[2]) if len(unit_data) > 2 else "unknown"
                    active_state = str(unit_data[3]) if len(unit_data) > 3 else "unknown"
                    sub_state = str(unit_data[4]) if len(unit_data) > 4 else "unknown"
                    unit_file_state = unit_file_states.get(name, "unknown")

                    discovered[name] = Service(
                        name=name,
                        description=description,
                        load_state=load_state,
                        active_state=active_state,
                        sub_state=sub_state,
                        unit_file_state=unit_file_state,
                        scope=valid_scope,
                    )

            # Add services present on disk in unit files that are inactive/unloaded
            for file_name, file_state in unit_file_states.items():
                if file_name not in discovered:
                    discovered[file_name] = Service(
                        name=file_name,
                        description="",
                        load_state="loaded",
                        active_state="inactive",
                        sub_state="dead",
                        unit_file_state=file_state,
                        scope=valid_scope,
                    )

            return sorted(discovered.values(), key=lambda s: s.name)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error("[%s] Failed to list services over D-Bus: %s", valid_scope, exc)
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def get_service(self, name: str, scope: str = "user") -> Service:
        """Get properties for a single service by loading the unit via systemd Manager."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)

            # LoadUnit ensures systemd brings the unit into memory to query properties
            load_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="LoadUnit",
                    signature="s",
                    body=[normalized_name],
                )
            )
            if load_reply.message_type == MessageType.ERROR:
                self._handle_error_reply(load_reply, "get_service", normalized_name, valid_scope)

            unit_path = str(load_reply.body[0])

            # Query unit properties
            props_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=unit_path,
                    interface=self.PROPERTIES_INTERFACE,
                    member="GetAll",
                    signature="s",
                    body=[self.UNIT_INTERFACE],
                )
            )
            if props_reply.message_type == MessageType.ERROR:
                self._handle_error_reply(props_reply, "get_service", normalized_name, valid_scope)

            props = props_reply.body[0] if props_reply.body else {}

            load_state = (
                self._get_variant_value(props.get("LoadState"))
                if "LoadState" in props
                else "unknown"
            )

            # If load_state is not-found, the unit is not installed on this system
            if load_state == "not-found":
                raise ServiceNotFoundError(normalized_name)

            desc = (
                self._get_variant_value(props.get("Description")) if "Description" in props else ""
            )
            active_state = (
                self._get_variant_value(props.get("ActiveState"))
                if "ActiveState" in props
                else "unknown"
            )
            sub_state = (
                self._get_variant_value(props.get("SubState")) if "SubState" in props else "unknown"
            )
            unit_file_state = (
                self._get_variant_value(props.get("UnitFileState"))
                if "UnitFileState" in props
                else "unknown"
            )

            return Service(
                name=normalized_name,
                description=desc,
                load_state=load_state,
                active_state=active_state,
                sub_state=sub_state,
                unit_file_state=unit_file_state,
                scope=valid_scope,
            )

        except (ServiceNotFoundError, PermissionDeniedError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to get service '%s' over D-Bus: %s",
                valid_scope,
                normalized_name,
                exc,
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def _call_unit_lifecycle_method(
        self,
        method: str,
        name: str,
        scope: str = "user",
        mode: str = "replace",
    ) -> None:
        """Generic handler for lifecycle operations (StartUnit, StopUnit, RestartUnit, ReloadUnit)."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member=method,
                    signature="ss",
                    body=[normalized_name, mode],
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(
                    reply, method.lower().removesuffix("unit"), normalized_name, valid_scope
                )

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed lifecycle method %s for '%s': %s",
                valid_scope,
                method,
                normalized_name,
                exc,
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def start_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Start a systemd service."""
        await self._call_unit_lifecycle_method("StartUnit", name, scope, mode)

    async def stop_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Stop a systemd service."""
        await self._call_unit_lifecycle_method("StopUnit", name, scope, mode)

    async def restart_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Restart a systemd service."""
        await self._call_unit_lifecycle_method("RestartUnit", name, scope, mode)

    async def reload_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        """Reload a systemd service."""
        await self._call_unit_lifecycle_method("ReloadUnit", name, scope, mode)

    async def enable_service(self, name: str, scope: str = "user") -> None:
        """Enable a service unit using EnableUnitFiles."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="EnableUnitFiles",
                    signature="asbb",
                    body=[[normalized_name], False, False],
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(reply, "enable", normalized_name, valid_scope)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to enable service '%s': %s", valid_scope, normalized_name, exc
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def disable_service(self, name: str, scope: str = "user") -> None:
        """Disable a service unit using DisableUnitFiles."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="DisableUnitFiles",
                    signature="asb",
                    body=[[normalized_name], False],
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(reply, "disable", normalized_name, valid_scope)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to disable service '%s': %s", valid_scope, normalized_name, exc
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def mask_service(self, name: str, scope: str = "user") -> None:
        """Mask a systemd service, preventing it from starting."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="MaskUnitFiles",
                    signature="asbb",
                    body=[[normalized_name], False, True],
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(reply, "mask", normalized_name, valid_scope)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error("[%s] Failed to mask service '%s': %s", valid_scope, normalized_name, exc)
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def unmask_service(self, name: str, scope: str = "user") -> None:
        """Unmask a systemd service."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="UnmaskUnitFiles",
                    signature="asb",
                    body=[[normalized_name], False],
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(reply, "unmask", normalized_name, valid_scope)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to unmask service '%s': %s", valid_scope, normalized_name, exc
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def reload_daemon(self, scope: str = "user") -> None:
        """Reload systemd manager configuration (equivalent to systemctl daemon-reload)."""
        valid_scope = validate_scope(scope)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="Reload",
                    flags=self._get_message_flags(valid_scope),
                )
            )
            if reply.message_type == MessageType.ERROR:
                self._handle_error_reply(reply, "reload-daemon", "systemd", valid_scope)

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error("[%s] Failed to reload systemd daemon: %s", valid_scope, exc)
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def _get_unit_object_path(self, bus: Any, normalized_name: str, valid_scope: str) -> str:
        """Helper to retrieve or load the D-Bus object path for a given service unit."""
        load_reply = await bus.call(
            Message(
                destination=self.SYSTEMD_BUS_NAME,
                path=self.SYSTEMD_OBJECT_PATH,
                interface=self.MANAGER_INTERFACE,
                member="LoadUnit",
                signature="s",
                body=[normalized_name],
            )
        )
        if load_reply.message_type == MessageType.ERROR:
            self._handle_error_reply(load_reply, "get_unit", normalized_name, valid_scope)
        return str(load_reply.body[0])

    async def get_unit_file(self, name: str, scope: str = "user") -> tuple[str | None, str]:
        """Retrieve the on-disk unit file fragment path and content."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            unit_path = await self._get_unit_object_path(bus, normalized_name, valid_scope)

            # Query FragmentPath from Unit interface
            reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=unit_path,
                    interface=self.PROPERTIES_INTERFACE,
                    member="Get",
                    signature="ss",
                    body=[self.UNIT_INTERFACE, "FragmentPath"],
                )
            )
            fragment_path: str | None = None
            if reply.message_type != MessageType.ERROR and reply.body:
                val = self._get_variant_value(reply.body[0])
                if val:
                    fragment_path = val

            if fragment_path and os.path.isfile(fragment_path):
                try:
                    content = Path(fragment_path).read_text(encoding="utf-8", errors="replace")
                    return fragment_path, content
                except Exception as exc:
                    return fragment_path, f"# Error reading unit file at {fragment_path}: {exc}"

            return None, (
                f"# No on-disk unit file found for '{normalized_name}'\n"
                f"# FragmentPath: {fragment_path or '(empty)'}\n"
                f"# This unit may be transient, generated, or masked in memory."
            )

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to get unit file for '%s': %s", valid_scope, normalized_name, exc
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def get_service_resources(self, name: str, scope: str = "user") -> ServiceResourceUsage:
        """Retrieve runtime resource metrics for an active service."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        try:
            bus = await self._connection_manager.get_bus(valid_scope)
            unit_path = await self._get_unit_object_path(bus, normalized_name, valid_scope)

            # 1. Query Unit properties
            unit_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=unit_path,
                    interface=self.PROPERTIES_INTERFACE,
                    member="GetAll",
                    signature="s",
                    body=[self.UNIT_INTERFACE],
                )
            )
            unit_props = unit_reply.body[0] if unit_reply.body else {}
            active_state = self._get_variant_value(unit_props.get("ActiveState"))
            is_active = active_state == "active"

            raw_enter = unit_props.get("ActiveEnterTimestamp")
            enter_val = getattr(raw_enter, "value", raw_enter) if raw_enter is not None else None
            active_enter_timestamp = (
                int(enter_val)
                if isinstance(enter_val, (int, float)) and 0 < enter_val < self.UNAVAILABLE_COUNTER
                else None
            )

            # 2. Query Service properties
            svc_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=unit_path,
                    interface=self.PROPERTIES_INTERFACE,
                    member="GetAll",
                    signature="s",
                    body=[self.SERVICE_INTERFACE],
                )
            )
            svc_props = svc_reply.body[0] if svc_reply.body else {}

            def _clean_uint64(val_obj: Any) -> int | None:
                if val_obj is None:
                    return None
                raw = getattr(val_obj, "value", val_obj)
                if isinstance(raw, (int, float)) and 0 <= raw < self.UNAVAILABLE_COUNTER:
                    return int(raw)
                return None

            cpu_usage = _clean_uint64(svc_props.get("CPUUsageNSec"))
            memory_current = _clean_uint64(svc_props.get("MemoryCurrent"))
            io_read = _clean_uint64(svc_props.get("IOReadBytes"))
            io_write = _clean_uint64(svc_props.get("IOWriteBytes"))
            tasks_current = _clean_uint64(svc_props.get("TasksCurrent"))

            main_pid_raw = svc_props.get("MainPID")
            main_pid_val = (
                getattr(main_pid_raw, "value", main_pid_raw) if main_pid_raw is not None else None
            )
            main_pid = (
                int(main_pid_val) if isinstance(main_pid_val, int) and main_pid_val > 0 else None
            )

            # 3. Query GetProcesses for process count
            process_count: int | None = None
            try:
                proc_reply = await bus.call(
                    Message(
                        destination=self.SYSTEMD_BUS_NAME,
                        path=unit_path,
                        interface=self.SERVICE_INTERFACE,
                        member="GetProcesses",
                    )
                )
                if proc_reply.message_type != MessageType.ERROR and proc_reply.body:
                    process_count = len(proc_reply.body[0])
            except Exception:
                process_count = None

            return ServiceResourceUsage(
                service=normalized_name,
                scope=valid_scope,
                is_active=is_active,
                cpu_usage_nsec=cpu_usage,
                memory_current=memory_current,
                io_read_bytes=io_read,
                io_write_bytes=io_write,
                tasks_current=tasks_current,
                process_count=process_count,
                active_enter_timestamp_usec=active_enter_timestamp,
                main_pid=main_pid,
            )

        except (PermissionDeniedError, ServiceNotFoundError, ServiceOperationError):
            raise
        except Exception as exc:
            logger.error(
                "[%s] Failed to get resources for '%s': %s", valid_scope, normalized_name, exc
            )
            raise SystemdConnectionError(
                f"Failed to communicate with {valid_scope} systemd: {exc}"
            ) from exc

    async def get_service_logs(self, name: str, lines: int = 200, scope: str = "user") -> str:
        """Retrieve recent journal log entries for a service unit."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)
        safe_lines = max(1, min(2000, lines))

        cmd = (
            ["journalctl", "-u", normalized_name, "-n", str(safe_lines), "--no-pager"]
            if valid_scope == "system"
            else [
                "journalctl",
                "--user-unit",
                normalized_name,
                "-n",
                str(safe_lines),
                "--no-pager",
            ]
        )

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_text = stderr.decode(errors="replace").strip()
                return f"# journalctl exited with status {proc.returncode}: {err_text}"
            return stdout.decode(errors="replace")
        except Exception as exc:
            logger.error(
                "[%s] Failed to retrieve logs for '%s': %s", valid_scope, normalized_name, exc
            )
            return f"# Failed to execute journalctl: {exc}"

    async def create_service(
        self, name: str, content: str, scope: str = "user", overwrite: bool = False
    ) -> str:
        """Create and install a new systemd unit file and reload daemon."""
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)

        if "[Unit]" not in content or "[Service]" not in content:
            raise ServiceOperationError(
                normalized_name,
                "create",
                "Unit file content must contain both [Unit] and [Service] sections.",
            )

        if valid_scope == "user":
            target_dir = Path.home() / ".config" / "systemd" / "user"
        else:
            target_dir = Path("/etc/systemd/system")

        target_file = target_dir / normalized_name

        if target_file.exists() and not overwrite:
            raise ServiceOperationError(
                normalized_name,
                "create",
                f"Service unit file already exists at '{target_file}'. Pass overwrite=True to replace.",
            )

        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            target_file.write_text(content, encoding="utf-8")
        except PermissionError as exc:
            raise AuthorizationDeniedError(
                action="create",
                service_name=normalized_name,
                reason=f"Permission denied writing to '{target_file}'. Creating system services requires administrative privileges.",
            ) from exc
        except OSError as exc:
            raise ServiceOperationError(
                normalized_name, "create", f"Failed to write unit file: {exc}"
            ) from exc

        # Trigger daemon-reload so systemd picks up the new unit immediately
        await self.reload_daemon(scope=valid_scope)
        logger.info("[%s] Created unit file at %s and reloaded daemon", valid_scope, target_file)
        return str(target_file)

    # --- Live updates ---

    async def _call_bus_daemon(self, bus: Any, member: str, rule: str) -> None:
        """Call ``AddMatch``/``RemoveMatch`` on the bus daemon."""
        reply = await bus.call(
            Message(
                destination=self.DBUS_BUS_NAME,
                path=self.DBUS_OBJECT_PATH,
                interface=self.DBUS_BUS_NAME,
                member=member,
                signature="s",
                body=[rule],
            )
        )
        if reply.message_type == MessageType.ERROR:
            raise SystemdConnectionError(f"D-Bus {member} failed: {reply.error_name}")

    async def _call_manager(self, bus: Any, member: str) -> Message:
        return await bus.call(
            Message(
                destination=self.SYSTEMD_BUS_NAME,
                path=self.SYSTEMD_OBJECT_PATH,
                interface=self.MANAGER_INTERFACE,
                member=member,
            )
        )

    async def _subscribe(self, bus: Any) -> None:
        """Ask systemd to emit unit signals; reference-counted per bus connection."""
        count = self._subscribers.get(bus, 0)
        self._subscribers[bus] = count + 1
        if count:
            return
        reply = await self._call_manager(bus, "Subscribe")
        # Older systemd answers a repeated Subscribe with AlreadySubscribed; that is fine.
        if reply.message_type == MessageType.ERROR and "AlreadySubscribed" not in (
            reply.error_name or ""
        ):
            self._subscribers.pop(bus, None)
            self._handle_error_reply(reply, "subscribe", "systemd")

    async def _unsubscribe(self, bus: Any) -> None:
        count = self._subscribers.get(bus, 0) - 1
        if count > 0:
            self._subscribers[bus] = count
            return
        self._subscribers.pop(bus, None)
        if bus.connected:
            with contextlib.suppress(Exception):
                await self._call_manager(bus, "Unsubscribe")

    async def _snapshot_service(self, bus: Any, name: str, scope: str) -> Service | None:
        """Current state of ``name`` without loading it (``None`` if it no longer exists).

        ``LoadUnit`` is avoided on purpose: loading a unit systemd just garbage-collected
        would emit ``UnitNew`` and fight the collector forever.
        """
        reply = await bus.call(
            Message(
                destination=self.SYSTEMD_BUS_NAME,
                path=self.SYSTEMD_OBJECT_PATH,
                interface=self.MANAGER_INTERFACE,
                member="GetUnit",
                signature="s",
                body=[name],
            )
        )
        if reply.message_type == MessageType.ERROR:
            # Not loaded: it still exists if a unit file is installed for it.
            file_reply = await bus.call(
                Message(
                    destination=self.SYSTEMD_BUS_NAME,
                    path=self.SYSTEMD_OBJECT_PATH,
                    interface=self.MANAGER_INTERFACE,
                    member="GetUnitFileState",
                    signature="s",
                    body=[name],
                )
            )
            if file_reply.message_type == MessageType.ERROR or not file_reply.body:
                return None
            return Service(
                name=name,
                description="",
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
                unit_file_state=str(file_reply.body[0]),
                scope=scope,
            )

        props_reply = await bus.call(
            Message(
                destination=self.SYSTEMD_BUS_NAME,
                path=str(reply.body[0]),
                interface=self.PROPERTIES_INTERFACE,
                member="GetAll",
                signature="s",
                body=[self.UNIT_INTERFACE],
            )
        )
        if props_reply.message_type == MessageType.ERROR or not props_reply.body:
            return None
        props = props_reply.body[0]

        def prop(key: str, default: str = "unknown") -> str:
            return self._get_variant_value(props[key]) if key in props else default

        return Service(
            name=name,
            description=prop("Description", ""),
            load_state=prop("LoadState"),
            active_state=prop("ActiveState"),
            sub_state=prop("SubState"),
            unit_file_state=prop("UnitFileState") or "unknown",
            scope=scope,
        )

    async def watch_services(self, scope: str = "user") -> AsyncIterator[ServiceEvent]:
        """Yield live service changes from systemd's D-Bus signals.

        The first event is ``ready``, sent once the signal subscription is in place, so a
        caller can list services after it without missing changes in between. The watch
        ends with ``SystemdConnectionError`` if the bus connection is lost.
        """
        valid_scope = validate_scope(scope)
        bus = await self._connection_manager.get_bus(valid_scope)
        pending: set[str] = set()
        resync = False
        wake = asyncio.Event()

        def on_message(msg: Message) -> None:
            nonlocal resync
            if msg.message_type != MessageType.SIGNAL:
                return
            name: str | None = None
            if msg.interface == self.PROPERTIES_INTERFACE and msg.member == "PropertiesChanged":
                if msg.body and msg.body[0] == self.UNIT_INTERFACE:
                    name = unit_name_from_path(msg.path or "")
            elif msg.interface == self.MANAGER_INTERFACE and msg.path == self.SYSTEMD_OBJECT_PATH:
                if msg.member in ("UnitNew", "UnitRemoved") and msg.body:
                    name = str(msg.body[0])
                elif msg.member == "UnitFilesChanged" or (
                    msg.member == "Reloading" and msg.body and msg.body[0] is False
                ):
                    resync = True
                    wake.set()
                    return
            if name and name.endswith(".service"):
                pending.add(name)
                wake.set()

        bus.add_message_handler(on_message)
        added_rules: list[str] = []
        subscribed = False
        try:
            try:
                for rule in self.WATCH_MATCH_RULES:
                    await self._call_bus_daemon(bus, "AddMatch", rule)
                    added_rules.append(rule)
                await self._subscribe(bus)
                subscribed = True
            except (PermissionDeniedError, ServiceOperationError, SystemdConnectionError):
                raise
            except Exception as exc:
                raise SystemdConnectionError(
                    f"Failed to watch {valid_scope} systemd for changes: {exc}"
                ) from exc

            yield ServiceEvent(kind="ready", scope=valid_scope)

            while True:
                try:
                    await asyncio.wait_for(wake.wait(), timeout=self.WATCH_LIVENESS_SECONDS)
                except TimeoutError:
                    if not bus.connected:
                        raise SystemdConnectionError(
                            f"Lost the {valid_scope} D-Bus connection while watching services."
                        ) from None
                    continue
                await asyncio.sleep(self.WATCH_DEBOUNCE_SECONDS)
                wake.clear()
                names, pending = pending, set()
                do_resync, resync = resync, False

                if do_resync:
                    yield ServiceEvent(kind="resync", scope=valid_scope)
                for name in sorted(names):
                    try:
                        service = await self._snapshot_service(bus, name, valid_scope)
                    except Exception as exc:
                        if not bus.connected:
                            raise SystemdConnectionError(
                                f"Lost the {valid_scope} D-Bus connection while watching services."
                            ) from exc
                        logger.debug("[%s] Could not read state of %s: %s", valid_scope, name, exc)
                        continue
                    if service is None:
                        yield ServiceEvent(kind="removed", scope=valid_scope, name=name)
                    else:
                        yield ServiceEvent(
                            kind="changed", scope=valid_scope, name=name, service=service
                        )
        finally:
            bus.remove_message_handler(on_message)
            if bus.connected:
                for rule in added_rules:
                    with contextlib.suppress(Exception):
                        await self._call_bus_daemon(bus, "RemoveMatch", rule)
            if subscribed:
                await self._unsubscribe(bus)

    @staticmethod
    def _journalctl_command(name: str, lines: int, scope: str, *, follow: bool) -> list[str]:
        unit_flag = "-u" if scope == "system" else "--user-unit"
        cmd = ["journalctl", unit_flag, name, "-n", str(lines), "--no-pager"]
        if follow:
            cmd.append("--follow")
        return cmd

    async def follow_service_logs(
        self, name: str, lines: int = 200, scope: str = "user"
    ) -> AsyncIterator[str]:
        """Yield the last ``lines`` journal lines of ``name``, then new lines as they arrive.

        Runs ``journalctl --follow``; the first item is ``""`` once it has started. The
        process is terminated when the caller stops iterating.
        """
        valid_scope = validate_scope(scope)
        normalized_name = normalize_service_name(name)
        safe_lines = max(0, min(2000, lines))
        cmd = self._journalctl_command(normalized_name, safe_lines, valid_scope, follow=True)

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            raise ServiceOperationError(
                normalized_name, "logs", f"Failed to execute journalctl: {exc}"
            ) from exc

        assert proc.stdout is not None
        try:
            yield ""
            while True:
                raw = await proc.stdout.readline()
                if not raw:
                    break
                yield raw.decode(errors="replace").rstrip("\n")
            status = await proc.wait()
            if status != 0:
                raise ServiceOperationError(
                    normalized_name, "logs", f"journalctl exited with status {status}"
                )
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.terminate()
                try:
                    await asyncio.wait_for(proc.wait(), timeout=2.0)
                except TimeoutError:
                    with contextlib.suppress(ProcessLookupError):
                        proc.kill()
                    await proc.wait()
