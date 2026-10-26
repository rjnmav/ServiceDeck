"""FastAPI dependencies for injecting core backend services."""

from typing import Annotated

from fastapi import Depends, Request

from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import SystemdConnectionError


def get_service_manager(request: Request) -> ServiceManager:
    """Retrieve the shared ServiceManager instance from application state."""
    manager: ServiceManager | None = getattr(request.app.state, "service_manager", None)
    if manager is None:
        raise SystemdConnectionError("ServiceManager is not initialized on application state.")
    return manager


def get_remote_manager(request: Request) -> RemoteManager:
    """Retrieve the shared RemoteManager instance from application state."""
    manager: RemoteManager | None = getattr(request.app.state, "remote_manager", None)
    if manager is None:
        raise SystemdConnectionError("RemoteManager is not initialized on application state.")
    return manager


ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]
RemoteManagerDep = Annotated[RemoteManager, Depends(get_remote_manager)]

__all__ = [
    "RemoteManagerDep",
    "ServiceManagerDep",
    "get_remote_manager",
    "get_service_manager",
]
