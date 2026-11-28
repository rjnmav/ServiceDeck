"""Asynchronous client for the ServiceDeck REST API."""

from typing import Any

from servicedeck.api_client.models.common import HealthInfo, ScopeInfo
from servicedeck.api_client.models.remote import (
    HostKeyInfo,
    KeySetupInfo,
    RemoteConnectionInfo,
    RemoteDevice,
)
from servicedeck.api_client.models.service import (
    CreatedService,
    DaemonReloadResult,
    OverrideResult,
    RevertResult,
    Service,
    ServiceLogs,
    ServiceOperationResult,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.api_client.transport import DEFAULT_TIMEOUT, ONBOARDING_TIMEOUT, AsyncTransport


class AsyncServiceDeckClient:
    """Asynchronous client for communicating with the ServiceDeck backend."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = DEFAULT_TIMEOUT,
        transport: AsyncTransport | None = None,
        target_device: str | None = None,
    ) -> None:
        self.transport = transport or AsyncTransport(base_url=base_url, timeout=timeout)
        self.target_device = target_device

    @property
    def base_url(self) -> str:
        """Return the base URL of the connected ServiceDeck backend."""
        return self.transport.base_url

    def _resolve_path(self, path: str, device_id: str | None = None) -> str:
        """Resolve route path targeting either the local machine or a remote device."""
        target = device_id if device_id is not None else self.target_device
        if target is None:
            return f"/api{path}"
        return f"/api/remote/{target}{path}"

    # --- System / General ---

    async def health(self) -> HealthInfo:
        """Check backend health and connection status to systemd buses."""
        data = await self.transport.request("GET", "/api/health")
        return HealthInfo.from_dict(data)

    async def get_scope(self) -> ScopeInfo:
        """Retrieve the currently active service scope and supported scopes."""
        data = await self.transport.request("GET", "/api/scope")
        return ScopeInfo.from_dict(data)

    async def set_scope(self, scope: str) -> ScopeInfo:
        """Set the active service scope ('user' or 'system')."""
        data = await self.transport.request("POST", "/api/scope", json={"scope": scope})
        return ScopeInfo.from_dict(data)

    # --- Remote Device Management ---

    async def list_devices(self) -> list[RemoteDevice]:
        """List all configured remote SSH devices and their connection status."""
        data = await self.transport.request("GET", "/api/remote/devices")
        return [RemoteDevice.from_dict(item) for item in data]

    async def add_device(
        self,
        id: str,
        hostname: str,
        port: int = 22,
        username: str | None = None,
        display_name: str | None = None,
        ssh_key_path: str | None = None,
        agent_mode: str | None = None,
    ) -> RemoteDevice:
        """Register a new remote device configuration."""
        payload: dict[str, Any] = {
            "id": id,
            "hostname": hostname,
            "port": port,
            "display_name": display_name or id,
        }
        if username:
            payload["username"] = username
        if ssh_key_path:
            payload["ssh_key_path"] = ssh_key_path
        if agent_mode:
            payload["agent_mode"] = agent_mode
        data = await self.transport.request("POST", "/api/remote/devices", json=payload)
        return RemoteDevice.from_dict(data)

    async def remove_device(self, device_id: str) -> None:
        """Remove and disconnect a remote device configuration."""
        await self.transport.request("DELETE", f"/api/remote/devices/{device_id}")

    async def connect_device(self, device_id: str) -> RemoteConnectionInfo:
        """Establish an SSH transport connection and verify the remote agent."""
        data = await self.transport.request("POST", f"/api/remote/devices/{device_id}/connect")
        return RemoteConnectionInfo.from_dict(data)

    async def get_host_key(self, device_id: str) -> HostKeyInfo:
        """Fetch the device's SSH host key fingerprint and trust status."""
        data = await self.transport.request(
            "GET", f"/api/remote/devices/{device_id}/host-key", timeout=ONBOARDING_TIMEOUT
        )
        return HostKeyInfo.from_dict(data)

    async def trust_host_key(self, device_id: str, fingerprint: str) -> HostKeyInfo:
        """Trust the device's SSH host key after the user verified ``fingerprint``."""
        data = await self.transport.request(
            "POST",
            f"/api/remote/devices/{device_id}/host-key/trust",
            json={"fingerprint": fingerprint},
            timeout=ONBOARDING_TIMEOUT,
        )
        return HostKeyInfo.from_dict(data)

    async def setup_key(self, device_id: str, password: str) -> KeySetupInfo:
        """Install the SSH login key on the device using its password once.

        The password is sent only to the local backend, which uses it for a single SSH
        login and never stores it.
        """
        data = await self.transport.request(
            "POST",
            f"/api/remote/devices/{device_id}/setup-key",
            json={"password": password},
            timeout=ONBOARDING_TIMEOUT,
        )
        return KeySetupInfo.from_dict(data)

    async def elevate_device(self, device_id: str, password: str | None = None) -> bool:
        """Get administrator (root via sudo) access on the device for this connection.

        ``password`` is the remote sudo password; it goes only to the local backend, which
        uses it once and never stores it. ``None`` tries passwordless sudo.
        """
        body = {"password": password} if password is not None else {}
        data = await self.transport.request(
            "POST",
            f"/api/remote/devices/{device_id}/elevate",
            json=body,
            timeout=ONBOARDING_TIMEOUT,
        )
        return bool(data.get("elevated", False))

    async def drop_device_privileges(self, device_id: str) -> None:
        """Stop the device's root agent; system-service changes need elevation again."""
        await self.transport.request("POST", f"/api/remote/devices/{device_id}/drop-privileges")

    async def disconnect_device(self, device_id: str) -> None:
        """Terminate the SSH transport session to the specified device."""
        await self.transport.request("POST", f"/api/remote/devices/{device_id}/disconnect")

    async def get_device_status(self, device_id: str) -> RemoteConnectionInfo:
        """Query connection state and agent handshake info for a device."""
        data = await self.transport.request("GET", f"/api/remote/devices/{device_id}/status")
        return RemoteConnectionInfo.from_dict(data)

    # --- Services Operations (Local or Remote) ---

    async def list_services(
        self,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> list[Service]:
        """List systemd services for the local machine or target remote device."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path("/services", device_id=device_id)
        data = await self.transport.request("GET", endpoint, params=params)
        return [Service.from_dict(item) for item in data]

    async def get_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> Service:
        """Retrieve detailed properties for a single service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}", device_id=device_id)
        data = await self.transport.request("GET", endpoint, params=params)
        return Service.from_dict(data)

    async def start_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Start a service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/start", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def stop_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Stop a running service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/stop", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def restart_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Restart a service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/restart", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def reload_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Reload configuration of a service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/reload", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def enable_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Enable a service unit to start at boot."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/enable", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def disable_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Disable a service unit from starting at boot."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/disable", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def mask_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Mask a service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/mask", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def unmask_service(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceOperationResult:
        """Unmask a service unit."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/unmask", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return ServiceOperationResult.from_dict(data)

    async def reload_daemon(
        self,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> DaemonReloadResult:
        """Reload systemd daemon configuration."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path("/daemon/reload", device_id=device_id)
        data = await self.transport.request("POST", endpoint, params=params)
        return DaemonReloadResult.from_dict(data)

    async def get_unit_file(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceUnitFile:
        """Retrieve unit file fragment path and content for a service."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/unit-file", device_id=device_id)
        data = await self.transport.request("GET", endpoint, params=params)
        return ServiceUnitFile.from_dict(data)

    async def get_resources(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceResources:
        """Retrieve runtime resource metrics for a service."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/resources", device_id=device_id)
        data = await self.transport.request("GET", endpoint, params=params)
        return ServiceResources.from_dict(data)

    async def get_logs(
        self,
        name: str,
        lines: int = 200,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> ServiceLogs:
        """Retrieve recent journal log entries for a service unit."""
        params: dict[str, Any] = {"lines": lines}
        if scope is not None:
            params["scope"] = scope
        endpoint = self._resolve_path(f"/services/{name}/logs", device_id=device_id)
        data = await self.transport.request("GET", endpoint, params=params)
        return ServiceLogs.from_dict(data)

    async def create_service(
        self,
        name: str,
        content: str,
        scope: str | None = None,
        overwrite: bool = False,
        device_id: str | None = None,
    ) -> CreatedService:
        """Create a custom service unit and install it on the system."""
        payload = {
            "name": name,
            "content": content,
            "scope": scope,
            "overwrite": overwrite,
        }
        endpoint = self._resolve_path("/services/create", device_id=device_id)
        data = await self.transport.request("POST", endpoint, json=payload)
        return CreatedService.from_dict(data)

    async def write_override(
        self,
        name: str,
        content: str,
        scope: str | None = None,
        drop_in: str = "override.conf",
        device_id: str | None = None,
    ) -> OverrideResult:
        """Write a drop-in override (``systemctl edit``) and reload systemd.

        Comment-only content removes the drop-in. If systemd rejects the result, the
        backend restores the previous file and raises ``ServiceOperationError``.
        """
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/override", device_id=device_id)
        data = await self.transport.request(
            "PUT", endpoint, params=params, json={"content": content, "drop_in": drop_in}
        )
        return OverrideResult.from_dict(data)

    async def revert_overrides(
        self,
        name: str,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> RevertResult:
        """Delete the unit's editable drop-ins (back to the vendor unit) and reload."""
        params = {"scope": scope} if scope is not None else None
        endpoint = self._resolve_path(f"/services/{name}/override", device_id=device_id)
        data = await self.transport.request("DELETE", endpoint, params=params)
        return RevertResult.from_dict(data)

    # --- Administrator access on this computer ---

    async def get_local_elevation(self) -> bool:
        """Whether system unit file changes on this computer currently run as root."""
        data = await self.transport.request("GET", "/api/elevation")
        return bool(data.get("elevated", False))

    async def elevate_local(self, password: str | None = None) -> bool:
        """Get administrator access on this computer (local root agent via sudo).

        The password goes only to the local backend, which answers sudo once and never
        stores it. ``None`` tries passwordless sudo.
        """
        body = {"password": password} if password is not None else {}
        data = await self.transport.request(
            "POST", "/api/elevation", json=body, timeout=ONBOARDING_TIMEOUT
        )
        return bool(data.get("elevated", False))

    async def drop_local_elevation(self) -> None:
        """Stop the local root agent; system unit file changes need the password again."""
        await self.transport.request("DELETE", "/api/elevation")

    async def close(self) -> None:
        """Close the underlying transport resources."""
        await self.transport.close()

    async def __aenter__(self) -> "AsyncServiceDeckClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()
