"""RemoteManager orchestrating remote SSH connections and service operations."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import Any

from servicedeck.backend.core.security_logger import log_remote_elevation
from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteElevationRequiredError,
    ServiceDeckError,
)
from servicedeck.backend.models.service import Service, ServiceEvent, ServiceResourceUsage
from servicedeck.backend.models.unit_files import (
    DEFAULT_DROP_IN,
    OverrideResult,
    UnitFileInfo,
    override_result_from_dict,
    unit_info_from_dict,
)
from servicedeck.backend.remote.channel import RemoteStream
from servicedeck.backend.remote.connection import RemoteConnectionManager
from servicedeck.backend.remote.device_config import DeviceConfigManager, RemoteDevice
from servicedeck.backend.remote.errors import (
    ELEVATION_CODES,
    error_parts,
    exception_from_response,
)
from servicedeck.backend.remote.key_setup import KeySetupResult, setup_key
from servicedeck.backend.remote.keys import ServiceDeckKeyStore
from servicedeck.backend.remote.known_hosts import HostKeyInfo
from servicedeck.remote.models import ErrorDetail, HelloMessage, RequestMessage, ResponseMessage

logger = logging.getLogger(__name__)


class RemoteManager:
    """Manages remote machines, their persistent device metadata, and remote systemd operations over SSH."""

    def __init__(
        self,
        connection_manager: RemoteConnectionManager | None = None,
        config_manager: DeviceConfigManager | None = None,
        key_store: ServiceDeckKeyStore | None = None,
    ) -> None:
        self._connections = connection_manager or RemoteConnectionManager()
        self._config = config_manager or DeviceConfigManager()
        self._keys = key_store or ServiceDeckKeyStore()
        self._next_request_id = 1

    @property
    def connection_manager(self) -> RemoteConnectionManager:
        """Return the underlying RemoteConnectionManager."""
        return self._connections

    @property
    def config_manager(self) -> DeviceConfigManager:
        """Return the underlying DeviceConfigManager."""
        return self._config

    def _get_next_id(self) -> int:
        """Allocate an incrementing request ID."""
        req_id = self._next_request_id
        self._next_request_id += 1
        return req_id

    # --- Device Configuration Management ---

    def list_devices(self) -> list[RemoteDevice]:
        """Return all saved remote devices."""
        return self._config.load_devices()

    def get_device(self, device_id: str) -> RemoteDevice | None:
        """Return a single saved device by identifier."""
        return self._config.get_device(device_id)

    def add_device(self, device: RemoteDevice) -> RemoteDevice:
        """Persist a new or updated remote device configuration."""
        self._config.save_device(device)
        return device

    async def remove_device(self, device_id: str) -> bool:
        """Disconnect and remove a remote device from saved configuration."""
        await self._connections.disconnect(device_id)
        return self._config.remove_device(device_id)

    def _require_device(self, device_id: str) -> RemoteDevice:
        device = self._config.get_device(device_id)
        if device is None:
            raise RemoteConnectionError(
                f"Device '{device_id}' is not configured.",
                details={"device_id": device_id},
            )
        return device

    # --- First-connection onboarding (host-key trust, SSH key setup) ---

    async def check_host_key(self, device_id: str) -> HostKeyInfo:
        """Fetch the device's SSH host key and report whether it is trusted."""
        device = self._require_device(device_id)
        return await self._connections.known_hosts.check(device.hostname, device.port)

    async def trust_host_key(self, device_id: str, fingerprint: str) -> HostKeyInfo:
        """Trust the device's host key, provided it still matches ``fingerprint``."""
        device = self._require_device(device_id)
        return await self._connections.known_hosts.trust(device.hostname, device.port, fingerprint)

    async def setup_key(self, device_id: str, password: str) -> KeySetupResult:
        """Install a login key on the device using its password once, then save the device.

        The password is only forwarded to the one-time SSH login; it is never stored.
        """
        device = self._require_device(device_id)
        await self._connections.disconnect(device_id)
        result = await setup_key(
            device,
            password,
            key_store=self._keys,
            known_hosts=self._connections.known_hosts,
        )
        self._config.save_device(result.device)
        return result

    # --- Connection Lifecycle ---

    async def connect(self, device_id: str, timeout: float = 15.0) -> HelloMessage:
        """Explicitly initiate an SSH connection to device_id."""
        device = self._config.get_device(device_id)
        if device is None:
            raise RemoteConnectionError(
                f"Device '{device_id}' is not configured.",
                details={"device_id": device_id},
            )
        return await self._connections.connect(device, timeout=timeout)

    async def disconnect(self, device_id: str) -> None:
        """Disconnect active SSH connection to device_id."""
        await self._connections.disconnect(device_id)

    async def disconnect_all(self) -> None:
        """Disconnect all active SSH connections."""
        await self._connections.disconnect_all()

    def is_connected(self, device_id: str) -> bool:
        """Return True if device_id currently has an active SSH session."""
        return self._connections.is_connected(device_id)

    # --- Administrator access (root agent via sudo) ---

    def is_elevated(self, device_id: str) -> bool:
        """Return True if system-scope calls for device_id currently run as root."""
        return self._connections.is_elevated(device_id)

    async def elevate(self, device_id: str, password: str | None) -> HelloMessage:
        """Get administrator access on device_id for the rest of this connection.

        Connects first if needed. ``password`` answers sudo once and is not stored;
        ``None`` tries passwordless sudo.
        """
        device = self._require_device(device_id)
        if not self._connections.is_connected(device_id):
            await self._connections.connect(device)
        try:
            hello = await self._connections.elevate(device_id, password)
        except RemoteConnectionError as exc:
            log_remote_elevation(
                "denied", device_id, hostname=device.hostname, reason=type(exc).__name__
            )
            raise
        log_remote_elevation("granted", device_id, hostname=device.hostname)
        return hello

    async def drop_privileges(self, device_id: str) -> None:
        """Stop the root agent on device_id; system-scope changes need elevation again."""
        was_elevated = self._connections.is_elevated(device_id)
        await self._connections.drop_privileges(device_id)
        if was_elevated:
            log_remote_elevation("dropped", device_id)

    def list_connected(self) -> list[str]:
        """Return a list of currently connected device IDs."""
        return self._connections.list_connected()

    # --- Remote Service Execution Core ---

    async def _execute(
        self,
        device_id: str,
        method: str,
        params: dict[str, Any] | None = None,
        timeout: float = 30.0,
    ) -> Any:
        """Execute a remote protocol method on device_id, raising domain exceptions on error.

        System-scope calls go to the root agent while the device is elevated. They are
        never silently retried as the normal user once administrator access has ended.
        """
        scope = (params or {}).get("scope")
        if scope == "system" and self._connections.is_elevated(device_id):
            transport = self._connections.get_transport(device_id)
            if transport is not None:
                request = RequestMessage(id=self._get_next_id(), method=method, params=params or {})
                try:
                    response = await transport.send_privileged_request(request, timeout=timeout)
                except RemoteConnectionError as exc:
                    raise RemoteElevationRequiredError(
                        "The administrator session ended; administrator access is needed again.",
                        details=self._elevation_details(device_id, method, params),
                    ) from exc
                return self._unwrap(device_id, method, params, response, privileged=True)

        transport = self._connections.get_transport(device_id)
        if transport is None:
            # Auto-connect if configured
            device = self._config.get_device(device_id)
            if device is None:
                raise RemoteConnectionError(
                    f"Device '{device_id}' is not configured.",
                    details={"device_id": device_id},
                )
            await self._connections.connect(device)
            transport = self._connections.get_transport(device_id)
            if transport is None:
                raise RemoteConnectionError(
                    f"Failed to establish connection to '{device_id}'.",
                    details={"device_id": device_id},
                )

        req_id = self._get_next_id()
        request = RequestMessage(id=req_id, method=method, params=params or {})
        try:
            response = await transport.send_request(request, timeout=timeout)
        except RemoteConnectionError:
            # Stale or broken transport detected: prune connection and attempt single reconnect retry
            await self._connections.disconnect(device_id)
            device = self._config.get_device(device_id)
            if device is not None:
                logger.info(
                    "Connection to '%s' lost during '%s'; attempting automatic reconnection...",
                    device_id,
                    method,
                )
                try:
                    await self._connections.connect(device)
                    new_transport = self._connections.get_transport(device_id)
                    if new_transport is not None:
                        response = await new_transport.send_request(request, timeout=timeout)
                    else:
                        raise
                except Exception:
                    raise
            else:
                raise

        return self._unwrap(device_id, method, params, response)

    async def _ensure_transport(self, device_id: str) -> Any:
        transport = self._connections.get_transport(device_id)
        if transport is None:
            await self._connections.connect(self._require_device(device_id))
            transport = self._connections.get_transport(device_id)
            if transport is None:
                raise RemoteConnectionError(
                    f"Failed to establish connection to '{device_id}'.",
                    details={"device_id": device_id},
                )
        return transport

    async def _open_stream(
        self, device_id: str, method: str, params: dict[str, Any], *, privileged: bool = False
    ) -> RemoteStream:
        """Open an agent stream, raising the domain error if the agent refuses it.

        ``privileged`` streams run on the root agent when the device is elevated.
        """
        transport = await self._ensure_transport(device_id)
        request = RequestMessage(id=self._get_next_id(), method=method, params=params)
        use_root = privileged and self._connections.is_elevated(device_id)
        if use_root:
            response, stream = await transport.open_privileged_stream(request)
        else:
            response, stream = await transport.open_stream(request)
        if stream is None:
            self._unwrap(device_id, method, params, response, privileged=use_root)
            raise ServiceDeckError(f"The agent on '{device_id}' did not open the stream.")
        return stream

    def _raise_stream_error(
        self, device_id: str, method: str, params: dict[str, Any], data: Any
    ) -> None:
        """Raise the domain error carried by a stream's ``end`` event, if any."""
        error = data.get("error") if isinstance(data, dict) else None
        if not isinstance(error, dict):
            return
        response = ResponseMessage(
            id=0,
            success=False,
            error=ErrorDetail(
                code=str(error.get("code", "")),
                message=str(error.get("message", "")),
                details=error.get("details") or {},
            ),
        )
        self._unwrap(device_id, method, params, response, privileged=True)

    async def watch_services(
        self, device_id: str, scope: str | None = None
    ) -> AsyncIterator[ServiceEvent]:
        """Stream live service changes from the remote host (first event: ``ready``)."""
        params: dict[str, Any] = {"scope": scope} if scope else {}
        resolved_scope = scope or "user"
        stream = await self._open_stream(device_id, "stream.services", params)
        try:
            yield ServiceEvent(kind="ready", scope=resolved_scope)
            async for event, data in stream:
                if event == "end":
                    self._raise_stream_error(device_id, "stream.services", params, data)
                    return
                payload = data if isinstance(data, dict) else {}
                event_scope = str(payload.get("scope") or resolved_scope)
                if event == "service":
                    service = Service(**payload)
                    yield ServiceEvent(
                        kind="changed", scope=service.scope, name=service.name, service=service
                    )
                elif event == "removed":
                    yield ServiceEvent(kind="removed", scope=event_scope, name=payload.get("name"))
                elif event == "resync":
                    yield ServiceEvent(kind="resync", scope=event_scope)
        finally:
            await stream.aclose()

    async def follow_service_logs(
        self, device_id: str, name: str, lines: int = 200, scope: str | None = None
    ) -> AsyncIterator[str]:
        """Stream journal lines from the remote host; the first item is ``""`` (ready).

        System-scope logs are read by the root agent while the device is elevated, which
        can see the whole journal.
        """
        params: dict[str, Any] = {"name": name, "lines": lines}
        if scope:
            params["scope"] = scope
        stream = await self._open_stream(
            device_id, "stream.logs", params, privileged=scope == "system"
        )
        try:
            yield ""
            async for event, data in stream:
                if event == "end":
                    self._raise_stream_error(device_id, "stream.logs", params, data)
                    return
                if event == "log" and isinstance(data, dict):
                    yield str(data.get("line", ""))
        finally:
            await stream.aclose()

    @staticmethod
    def _elevation_details(
        device_id: str, method: str, params: dict[str, Any] | None
    ) -> dict[str, Any]:
        return {
            "device_id": device_id,
            "action": method,
            "service_name": (params or {}).get("name"),
            "scope": (params or {}).get("scope"),
        }

    def _unwrap(
        self,
        device_id: str,
        method: str,
        params: dict[str, Any] | None,
        response: ResponseMessage,
        *,
        privileged: bool = False,
    ) -> Any:
        """Return a response's result, or raise the domain exception it describes.

        A permission-type failure of a system-scope call made as the normal user means
        administrator access is needed, so it becomes ``RemoteElevationRequiredError``.
        """
        if not response.success:
            code, msg, details = error_parts(response)
            if (
                not privileged
                and (params or {}).get("scope") == "system"
                and code in ELEVATION_CODES
            ):
                raise RemoteElevationRequiredError(
                    f"{msg} Administrator access on the remote host is required.",
                    details={
                        **details,
                        **self._elevation_details(device_id, method, params),
                    },
                )
            raise exception_from_response(method, params, response)

        return response.result

    # --- High-level Service Operations ---

    async def list_services(self, device_id: str, scope: str | None = None) -> list[Service]:
        """List systemd services on the specified remote host."""
        params: dict[str, Any] = {}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.list", params)
        return [Service(**item) for item in result]

    async def get_service(self, device_id: str, name: str, scope: str | None = None) -> Service:
        """Get details for a single service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.get", params)
        return Service(**result)

    async def start_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Start a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.start", params)

    async def stop_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Stop a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.stop", params)

    async def restart_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Restart a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.restart", params)

    async def reload_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Reload service configuration on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.reload", params)

    async def enable_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Enable a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.enable", params)

    async def disable_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Disable a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.disable", params)

    async def mask_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Mask a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.mask", params)

    async def unmask_service(self, device_id: str, name: str, scope: str | None = None) -> None:
        """Unmask a service on the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "service.unmask", params)

    async def reload_daemon(self, device_id: str, scope: str | None = None) -> None:
        """Execute daemon-reload on the remote host."""
        params: dict[str, Any] = {}
        if scope:
            params["scope"] = scope
        await self._execute(device_id, "daemon.reload", params)

    async def get_unit_file(
        self, device_id: str, name: str, scope: str | None = None
    ) -> tuple[str | None, str]:
        """Fetch unit file content from the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.unit_file", params)
        return result.get("path"), result.get("content", "")

    async def get_unit_info(
        self, device_id: str, name: str, scope: str | None = None
    ) -> UnitFileInfo:
        """Fetch the unit's main file plus drop-ins from the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.unit_info", params)
        return unit_info_from_dict(result)

    async def write_override(
        self,
        device_id: str,
        name: str,
        content: str,
        scope: str | None = None,
        drop_in: str = DEFAULT_DROP_IN,
    ) -> OverrideResult:
        """Write a drop-in override on the remote host and reload its systemd."""
        params: dict[str, Any] = {"name": name, "content": content, "drop_in": drop_in}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.override.write", params)
        return override_result_from_dict(result)

    async def revert_overrides(
        self, device_id: str, name: str, scope: str | None = None
    ) -> list[str]:
        """Remove a service's writable drop-ins on the remote host and reload."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.override.revert", params)
        return [str(path) for path in result.get("removed", [])]

    async def get_service_resources(
        self, device_id: str, name: str, scope: str | None = None
    ) -> ServiceResourceUsage:
        """Fetch runtime service resource usage from the remote host."""
        params: dict[str, Any] = {"name": name}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.resources", params)
        known = ServiceResourceUsage.__dataclass_fields__
        return ServiceResourceUsage(**{k: v for k, v in result.items() if k in known})

    async def get_service_logs(
        self, device_id: str, name: str, lines: int = 200, scope: str | None = None
    ) -> str:
        """Retrieve recent journal log entries from the remote host."""
        params: dict[str, Any] = {"name": name, "lines": lines}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.logs", params)
        return str(result.get("logs", ""))

    async def create_service(
        self,
        device_id: str,
        name: str,
        content: str,
        scope: str | None = None,
        overwrite: bool = False,
    ) -> str:
        """Create and install a unit file on the remote host."""
        params: dict[str, Any] = {
            "name": name,
            "content": content,
            "overwrite": overwrite,
        }
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "service.create", params)
        return str(result.get("path", ""))

    async def is_healthy(self, device_id: str, scope: str | None = None) -> bool:
        """Check systemd D-Bus health on the remote host."""
        params: dict[str, Any] = {}
        if scope:
            params["scope"] = scope
        result = await self._execute(device_id, "health.check", params)
        return bool(result.get("healthy", False))


__all__ = ["RemoteManager"]
