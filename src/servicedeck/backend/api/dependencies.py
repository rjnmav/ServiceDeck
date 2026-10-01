"""FastAPI dependencies for injecting core backend services."""

from fastapi import Request

from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import SystemdConnectionError


def get_service_manager(request: Request) -> ServiceManager:
    """Retrieve the shared ServiceManager instance from application state."""
    manager: ServiceManager | None = getattr(request.app.state, "service_manager", None)
    if manager is None:
        raise SystemdConnectionError("ServiceManager is not initialized on application state.")
    return manager
