"""Health check endpoints supporting user and system systemd connections."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from servicedeck.backend.api.dependencies import get_service_manager
from servicedeck.backend.config.settings import Settings, get_settings
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.schemas.service import HealthResponse

router = APIRouter(tags=["health"])

ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]
SettingsDep = Annotated[Settings, Depends(get_settings)]


@router.get(
    "/health",
    response_model=HealthResponse,
    status_code=status.HTTP_200_OK,
    summary="Health check",
    description="Check whether the backend API and user/system systemd D-Bus connections are operational.",
)
async def health_check(
    service_manager: ServiceManagerDep,
    settings: SettingsDep,
) -> HealthResponse:
    """Return backend health and connection status for both user and system buses."""
    user_connected = await service_manager.is_healthy("user")
    system_connected = await service_manager.is_healthy("system")

    if user_connected and system_connected:
        health_status = "ok"
    elif user_connected or system_connected:
        health_status = "degraded"
    else:
        health_status = "down"

    return HealthResponse(
        status=health_status,
        systemd_connected=user_connected or system_connected,
        systemd_user_connected=user_connected,
        systemd_system_connected=system_connected,
        active_scope=service_manager.get_active_scope(),
        version=settings.app_version,
        listen_address=f"{settings.host}:{settings.port}",
        allow_interactive_authorization=settings.allow_interactive_authorization,
    )
