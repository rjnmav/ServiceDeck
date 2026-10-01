"""Main API router combining all route modules."""

from fastapi import APIRouter

from servicedeck.backend.api.routes import daemon, health, scope, services

api_router = APIRouter(prefix="/api")

api_router.include_router(health.router)
api_router.include_router(scope.router)
api_router.include_router(services.router)
api_router.include_router(daemon.router)
