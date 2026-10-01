"""API route for querying and toggling the active service scope (user vs system)."""

from typing import Annotated

from fastapi import APIRouter, Depends, status

from servicedeck.backend.api.dependencies import get_service_manager
from servicedeck.backend.core.security_logger import log_scope_change
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.schemas.service import ScopeResponse, ScopeUpdateRequest

router = APIRouter(prefix="/scope", tags=["scope"])

ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]


@router.get(
    "",
    response_model=ScopeResponse,
    status_code=status.HTTP_200_OK,
    summary="Get active scope",
    description="Retrieve the currently active service scope ('user' or 'system') and available scopes.",
)
async def get_active_scope(
    service_manager: ServiceManagerDep,
) -> ScopeResponse:
    """Return the currently active service scope."""
    return ScopeResponse(active_scope=service_manager.get_active_scope())


@router.post(
    "",
    response_model=ScopeResponse,
    status_code=status.HTTP_200_OK,
    summary="Set active scope",
    description="Toggle the active service scope between 'user' and 'system'.",
)
async def set_active_scope(
    request: ScopeUpdateRequest,
    service_manager: ServiceManagerDep,
) -> ScopeResponse:
    """Set the active service scope."""
    old_scope = service_manager.get_active_scope()
    new_scope = service_manager.set_active_scope(request.scope)
    log_scope_change(old_scope=old_scope, new_scope=new_scope)
    return ScopeResponse(active_scope=new_scope)
