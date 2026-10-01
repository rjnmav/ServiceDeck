"""Systemd daemon management endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from servicedeck.backend.api.dependencies import get_service_manager
from servicedeck.backend.core.security_logger import (
    log_authorization_denied,
    log_operation_attempt,
    log_polkit_agent_unavailable,
)
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import AuthorizationDeniedError, PolkitAgentUnavailableError
from servicedeck.backend.models.service import ServiceScope
from servicedeck.backend.schemas.service import DaemonReloadResponse

router = APIRouter(prefix="/daemon", tags=["daemon"])

ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]
ScopeQuery = Annotated[
    ServiceScope | None,
    Query(
        description="Optional scope override ('user' or 'system'). If omitted, active scope is used.",
    ),
]


@router.post(
    "/reload",
    response_model=DaemonReloadResponse,
    status_code=status.HTTP_200_OK,
    summary="Reload systemd daemon",
    description="Reload systemd manager configuration (equivalent to systemctl daemon-reload).",
)
async def reload_daemon(
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> DaemonReloadResponse:
    """Trigger a daemon-reload on the systemd manager."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.reload_daemon(scope=resolved_scope)
        log_operation_attempt("reload_daemon", "*", resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("reload_daemon", "*", resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("reload_daemon", "*", resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("reload_daemon", "*", resolved_scope, "failed")
        raise
    return DaemonReloadResponse(
        success=True,
        scope=resolved_scope,
        message=f"[{resolved_scope}] systemd daemon reloaded successfully.",
    )
