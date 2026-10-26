"""Main API router combining all route modules."""

from fastapi import APIRouter

from servicedeck.backend.api.routes import (
    daemon,
    devices,
    health,
    remote,
    scope,
    services,
)

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(scope.router)
api_router.include_router(services.router)
api_router.include_router(daemon.router)
api_router.include_router(devices.router)
api_router.include_router(remote.router)

__all__ = ["api_router"]
