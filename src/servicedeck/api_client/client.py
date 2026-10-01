"""Synchronous client for the ServiceDeck REST API."""

from typing import Any

from servicedeck.api_client.models.common import HealthInfo, ScopeInfo
from servicedeck.api_client.models.service import (
    CreatedService,
    DaemonReloadResult,
    Service,
    ServiceLogs,
    ServiceOperationResult,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.api_client.transport import DEFAULT_TIMEOUT, SyncTransport


class ServiceDeckClient:
    """Synchronous client for communicating with the ServiceDeck backend."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = DEFAULT_TIMEOUT,
        transport: SyncTransport | None = None,
    ) -> None:
        self.transport = transport or SyncTransport(base_url=base_url, timeout=timeout)

    @property
    def base_url(self) -> str:
        """Return the base URL of the connected ServiceDeck backend."""
        return self.transport.base_url

    def health(self) -> HealthInfo:
        """Check backend health and connection status to systemd buses."""
        data = self.transport.request("GET", "/api/health")
        return HealthInfo.from_dict(data)

    def get_scope(self) -> ScopeInfo:
        """Retrieve the currently active service scope and supported scopes."""
        data = self.transport.request("GET", "/api/scope")
        return ScopeInfo.from_dict(data)

    def set_scope(self, scope: str) -> ScopeInfo:
        """Set the active service scope ('user' or 'system')."""
        data = self.transport.request("POST", "/api/scope", json={"scope": scope})
        return ScopeInfo.from_dict(data)

    def list_services(self, scope: str | None = None) -> list[Service]:
        """List systemd services for the active or specified scope."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("GET", "/api/services", params=params)
        return [Service.from_dict(item) for item in data]

    def get_service(self, name: str, scope: str | None = None) -> Service:
        """Retrieve detailed properties for a single service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("GET", f"/api/services/{name}", params=params)
        return Service.from_dict(data)

    def start_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Start a service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/start", params=params)
        return ServiceOperationResult.from_dict(data)

    def stop_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Stop a running service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/stop", params=params)
        return ServiceOperationResult.from_dict(data)

    def restart_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Restart a service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/restart", params=params)
        return ServiceOperationResult.from_dict(data)

    def reload_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Reload configuration of a service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/reload", params=params)
        return ServiceOperationResult.from_dict(data)

    def enable_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Enable a service unit to start at boot."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/enable", params=params)
        return ServiceOperationResult.from_dict(data)

    def disable_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Disable a service unit from starting at boot."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/disable", params=params)
        return ServiceOperationResult.from_dict(data)

    def mask_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Mask a service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/mask", params=params)
        return ServiceOperationResult.from_dict(data)

    def unmask_service(self, name: str, scope: str | None = None) -> ServiceOperationResult:
        """Unmask a service unit."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", f"/api/services/{name}/unmask", params=params)
        return ServiceOperationResult.from_dict(data)

    def reload_daemon(self, scope: str | None = None) -> DaemonReloadResult:
        """Reload systemd daemon configuration."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("POST", "/api/daemon/reload", params=params)
        return DaemonReloadResult.from_dict(data)

    def get_unit_file(self, name: str, scope: str | None = None) -> ServiceUnitFile:
        """Retrieve unit file fragment path and content for a service."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("GET", f"/api/services/{name}/unit-file", params=params)
        return ServiceUnitFile.from_dict(data)

    def get_resources(self, name: str, scope: str | None = None) -> ServiceResources:
        """Retrieve runtime resource metrics for a service."""
        params = {"scope": scope} if scope is not None else None
        data = self.transport.request("GET", f"/api/services/{name}/resources", params=params)
        return ServiceResources.from_dict(data)

    def get_logs(self, name: str, lines: int = 200, scope: str | None = None) -> ServiceLogs:
        """Retrieve recent journal log entries for a service unit."""
        params: dict[str, Any] = {"lines": lines}
        if scope is not None:
            params["scope"] = scope
        data = self.transport.request("GET", f"/api/services/{name}/logs", params=params)
        return ServiceLogs.from_dict(data)

    def create_service(
        self, name: str, content: str, scope: str | None = None, overwrite: bool = False
    ) -> CreatedService:
        """Create a custom service unit and install it on the system."""
        payload = {
            "name": name,
            "content": content,
            "scope": scope,
            "overwrite": overwrite,
        }
        data = self.transport.request("POST", "/api/services/create", json=payload)
        return CreatedService.from_dict(data)

    def close(self) -> None:
        """Close the underlying transport resources."""
        self.transport.close()

    def __enter__(self) -> "ServiceDeckClient":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
