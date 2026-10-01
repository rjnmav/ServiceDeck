"""Core service management logic with dynamic active scope support.

This module contains pure application/domain business logic.
It must NOT import or know anything about FastAPI, HTTP, or web frameworks.
"""

import logging

from servicedeck.backend.infrastructure.dbus.systemd import SystemdAdapter
from servicedeck.backend.models.service import (
    Service,
    ServiceResourceUsage,
    normalize_service_name,
    validate_scope,
)

logger = logging.getLogger(__name__)


class ServiceManager:
    """Manages Linux systemd services via an injected SystemdAdapter.

    Maintains active scope state ('user' by default), which can be toggled
    to 'system'. All operations resolve to the active scope when not explicitly specified.
    """

    def __init__(self, adapter: SystemdAdapter, default_scope: str = "user") -> None:
        self._adapter = adapter
        self._active_scope: str = validate_scope(default_scope)

    @property
    def active_scope(self) -> str:
        """Return the currently active service scope ('user' or 'system')."""
        return self._active_scope

    def get_active_scope(self) -> str:
        """Return the currently active service scope."""
        return self._active_scope

    def set_active_scope(self, scope: str) -> str:
        """Set the active service scope ('user' or 'system')."""
        self._active_scope = validate_scope(scope)
        logger.info("Active scope changed to '%s'", self._active_scope)
        return self._active_scope

    def resolve_scope(self, scope: str | None = None) -> str:
        """Resolve the target scope: uses provided scope if given, otherwise active_scope."""
        if scope is not None:
            return validate_scope(scope)
        return self._active_scope

    async def is_healthy(self, scope: str | None = None) -> bool:
        """Check if the underlying systemd service backend is healthy for the resolved scope."""
        target_scope = self.resolve_scope(scope)
        return await self._adapter.is_healthy(scope=target_scope)

    async def list_services(self, scope: str | None = None) -> list[Service]:
        """Retrieve a list of all discovered system services for the resolved scope."""
        target_scope = self.resolve_scope(scope)
        logger.debug("[%s] Listing all services", target_scope)
        return await self._adapter.list_services(scope=target_scope)

    async def get_service(self, name: str, scope: str | None = None) -> Service:
        """Retrieve details for a single system service by name for the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.debug("[%s] Getting service '%s'", target_scope, clean_name)
        return await self._adapter.get_service(clean_name, scope=target_scope)

    async def start_service(self, name: str, scope: str | None = None) -> None:
        """Start a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Starting service '%s'", target_scope, clean_name)
        await self._adapter.start_service(clean_name, scope=target_scope)

    async def stop_service(self, name: str, scope: str | None = None) -> None:
        """Stop a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Stopping service '%s'", target_scope, clean_name)
        await self._adapter.stop_service(clean_name, scope=target_scope)

    async def restart_service(self, name: str, scope: str | None = None) -> None:
        """Restart a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Restarting service '%s'", target_scope, clean_name)
        await self._adapter.restart_service(clean_name, scope=target_scope)

    async def reload_service(self, name: str, scope: str | None = None) -> None:
        """Reload configuration for a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Reloading service '%s'", target_scope, clean_name)
        await self._adapter.reload_service(clean_name, scope=target_scope)

    async def enable_service(self, name: str, scope: str | None = None) -> None:
        """Enable a system service to start automatically in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Enabling service '%s'", target_scope, clean_name)
        await self._adapter.enable_service(clean_name, scope=target_scope)

    async def disable_service(self, name: str, scope: str | None = None) -> None:
        """Disable a system service from starting automatically in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Disabling service '%s'", target_scope, clean_name)
        await self._adapter.disable_service(clean_name, scope=target_scope)

    async def mask_service(self, name: str, scope: str | None = None) -> None:
        """Mask a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Masking service '%s'", target_scope, clean_name)
        await self._adapter.mask_service(clean_name, scope=target_scope)

    async def unmask_service(self, name: str, scope: str | None = None) -> None:
        """Unmask a system service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info("[%s] Unmasking service '%s'", target_scope, clean_name)
        await self._adapter.unmask_service(clean_name, scope=target_scope)

    async def reload_daemon(self, scope: str | None = None) -> None:
        """Reload systemd manager configuration (daemon-reload) in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        logger.info("[%s] Reloading systemd daemon", target_scope)
        await self._adapter.reload_daemon(scope=target_scope)

    async def get_unit_file(self, name: str, scope: str | None = None) -> tuple[str | None, str]:
        """Retrieve unit file fragment path and content in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.debug("[%s] Getting unit file for '%s'", target_scope, clean_name)
        return await self._adapter.get_unit_file(clean_name, scope=target_scope)

    async def get_service_resources(
        self, name: str, scope: str | None = None
    ) -> ServiceResourceUsage:
        """Retrieve runtime resource metrics for a service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.debug("[%s] Getting resources for '%s'", target_scope, clean_name)
        return await self._adapter.get_service_resources(clean_name, scope=target_scope)

    async def get_service_logs(self, name: str, lines: int = 200, scope: str | None = None) -> str:
        """Retrieve recent journal log entries for a service in the resolved scope."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.debug("[%s] Getting logs for '%s' (%d lines)", target_scope, clean_name, lines)
        return await self._adapter.get_service_logs(clean_name, lines=lines, scope=target_scope)

    async def create_service(
        self, name: str, content: str, scope: str | None = None, overwrite: bool = False
    ) -> str:
        """Create a new service unit file in the resolved scope and reload daemon."""
        target_scope = self.resolve_scope(scope)
        clean_name = normalize_service_name(name)
        logger.info(
            "[%s] Creating service '%s' (overwrite=%s)", target_scope, clean_name, overwrite
        )
        return await self._adapter.create_service(
            clean_name, content=content, scope=target_scope, overwrite=overwrite
        )
