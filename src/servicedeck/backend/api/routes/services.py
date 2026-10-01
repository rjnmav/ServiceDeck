"""Service management and inspection endpoints supporting user and system scopes."""

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
from servicedeck.backend.models.service import ServiceScope, normalize_service_name
from servicedeck.backend.schemas.service import (
    CreateServiceRequest,
    CreateServiceResponse,
    ResourceUsageResponse,
    ServiceLogsResponse,
    ServiceOperationResponse,
    ServiceResponse,
    UnitFileResponse,
)

router = APIRouter(prefix="/services", tags=["services"])

ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]
ScopeQuery = Annotated[
    ServiceScope | None,
    Query(
        description="Optional scope override ('user' or 'system'). If omitted, active scope is used.",
    ),
]


@router.get(
    "",
    response_model=list[ServiceResponse],
    status_code=status.HTTP_200_OK,
    summary="List all services",
    description="Discover and return systemd services for the active scope (or specified scope).",
)
async def list_services(
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> list[ServiceResponse]:
    """Retrieve all discovered systemd services for the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    services = await service_manager.list_services(scope=resolved_scope)
    return [ServiceResponse.from_domain(s) for s in services]


@router.get(
    "/{service_name}",
    response_model=ServiceResponse,
    status_code=status.HTTP_200_OK,
    summary="Get service details",
    description="Retrieve properties and state for a specific service unit in the resolved scope.",
)
async def get_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceResponse:
    """Retrieve details for a single systemd service."""
    resolved_scope = service_manager.resolve_scope(scope)
    service = await service_manager.get_service(service_name, scope=resolved_scope)
    return ServiceResponse.from_domain(service)


@router.post(
    "/{service_name}/start",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Start service",
    description="Start an inactive systemd service unit.",
)
async def start_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Start the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.start_service(service_name, scope=resolved_scope)
        log_operation_attempt("start", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("start", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("start", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("start", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="start",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' started successfully.",
    )


@router.post(
    "/{service_name}/stop",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Stop service",
    description="Stop an active systemd service unit.",
)
async def stop_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Stop the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.stop_service(service_name, scope=resolved_scope)
        log_operation_attempt("stop", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("stop", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("stop", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("stop", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="stop",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' stopped successfully.",
    )


@router.post(
    "/{service_name}/restart",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Restart service",
    description="Restart an active or inactive systemd service unit.",
)
async def restart_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Restart the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.restart_service(service_name, scope=resolved_scope)
        log_operation_attempt("restart", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("restart", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("restart", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("restart", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="restart",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' restarted successfully.",
    )


@router.post(
    "/{service_name}/reload",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Reload service",
    description="Reload the configuration of a running systemd service unit.",
)
async def reload_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Reload configuration of the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.reload_service(service_name, scope=resolved_scope)
        log_operation_attempt("reload", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("reload", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("reload", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("reload", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="reload",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' reloaded successfully.",
    )


@router.post(
    "/{service_name}/enable",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Enable service",
    description="Enable a systemd service unit to start automatically at boot/login time.",
)
async def enable_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Enable the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.enable_service(service_name, scope=resolved_scope)
        log_operation_attempt("enable", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("enable", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("enable", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("enable", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="enable",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' enabled successfully.",
    )


@router.post(
    "/{service_name}/disable",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Disable service",
    description="Disable a systemd service unit from starting automatically at boot/login time.",
)
async def disable_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Disable the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.disable_service(service_name, scope=resolved_scope)
        log_operation_attempt("disable", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("disable", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("disable", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("disable", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="disable",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' disabled successfully.",
    )


@router.post(
    "/create",
    response_model=CreateServiceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create custom service",
    description="Create a new custom systemd service unit file and reload daemon.",
)
async def create_service(
    request: CreateServiceRequest,
    service_manager: ServiceManagerDep,
) -> CreateServiceResponse:
    """Create a new custom systemd service unit in the specified or active scope."""
    resolved_scope = service_manager.resolve_scope(request.scope)
    try:
        path = await service_manager.create_service(
            name=request.name,
            content=request.content,
            scope=resolved_scope,
            overwrite=request.overwrite,
        )
        log_operation_attempt("create", request.name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("create", request.name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("create", request.name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("create", request.name, resolved_scope, "failed")
        raise
    return CreateServiceResponse(
        success=True,
        service=request.name,
        path=path,
        scope=resolved_scope,
    )


@router.post(
    "/{service_name}/mask",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Mask service",
    description="Mask a systemd service unit, linking it to /dev/null to prevent starting.",
)
async def mask_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Mask the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.mask_service(service_name, scope=resolved_scope)
        log_operation_attempt("mask", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("mask", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("mask", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("mask", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="mask",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' masked successfully.",
    )


@router.post(
    "/{service_name}/unmask",
    response_model=ServiceOperationResponse,
    status_code=status.HTTP_200_OK,
    summary="Unmask service",
    description="Unmask a systemd service unit, removing the symlink to /dev/null.",
)
async def unmask_service(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ServiceOperationResponse:
    """Unmask the specified service in the resolved scope."""
    resolved_scope = service_manager.resolve_scope(scope)
    try:
        await service_manager.unmask_service(service_name, scope=resolved_scope)
        log_operation_attempt("unmask", service_name, resolved_scope, "success")
    except PolkitAgentUnavailableError:
        log_polkit_agent_unavailable("unmask", service_name, resolved_scope)
        raise
    except AuthorizationDeniedError as exc:
        log_authorization_denied("unmask", service_name, resolved_scope, str(exc))
        raise
    except Exception:
        log_operation_attempt("unmask", service_name, resolved_scope, "failed")
        raise
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="unmask",
        scope=resolved_scope,
        message=f"[{resolved_scope}] Service '{service_name}' unmasked successfully.",
    )


@router.get(
    "/{service_name}/unit-file",
    response_model=UnitFileResponse,
    status_code=status.HTTP_200_OK,
    summary="Get service unit file",
    description="Retrieve the on-disk unit file fragment path and content for a service.",
)
async def get_unit_file(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> UnitFileResponse:
    """Retrieve the on-disk unit file fragment path and content."""
    resolved_scope = service_manager.resolve_scope(scope)
    clean_name = normalize_service_name(service_name)
    path, content = await service_manager.get_unit_file(clean_name, scope=resolved_scope)
    return UnitFileResponse(
        service=clean_name,
        fragment_path=path,
        content=content,
        scope=resolved_scope,
    )


@router.get(
    "/{service_name}/resources",
    response_model=ResourceUsageResponse,
    status_code=status.HTTP_200_OK,
    summary="Get service resource metrics",
    description="Retrieve runtime resource usage metrics (CPU, memory, disk I/O, tasks, PID, uptime).",
)
async def get_service_resources(
    service_name: str,
    service_manager: ServiceManagerDep,
    scope: ScopeQuery = None,
) -> ResourceUsageResponse:
    """Retrieve runtime resource metrics for an active service."""
    resolved_scope = service_manager.resolve_scope(scope)
    clean_name = normalize_service_name(service_name)
    res = await service_manager.get_service_resources(clean_name, scope=resolved_scope)
    return ResourceUsageResponse(
        service=clean_name,
        cpu_usage_nsec=res.cpu_usage_nsec,
        memory_current_bytes=res.memory_current,
        disk_read_bytes=res.io_read_bytes,
        disk_write_bytes=res.io_write_bytes,
        tasks_current=res.tasks_current,
        main_pid=res.main_pid,
        active_enter_timestamp=res.active_enter_timestamp_usec,
        active_state="active" if res.is_active else "inactive",
        scope=resolved_scope,
    )


@router.get(
    "/{service_name}/logs",
    response_model=ServiceLogsResponse,
    status_code=status.HTTP_200_OK,
    summary="Get service logs",
    description="Retrieve recent journal log entries for a service unit.",
)
async def get_service_logs(
    service_name: str,
    service_manager: ServiceManagerDep,
    lines: Annotated[
        int, Query(ge=1, le=5000, description="Number of journal log lines to retrieve")
    ] = 200,
    scope: ScopeQuery = None,
) -> ServiceLogsResponse:
    """Retrieve recent journal log entries for a service unit."""
    resolved_scope = service_manager.resolve_scope(scope)
    clean_name = normalize_service_name(service_name)
    logs = await service_manager.get_service_logs(clean_name, lines=lines, scope=resolved_scope)
    return ServiceLogsResponse(
        service=clean_name,
        logs=logs,
        scope=resolved_scope,
        lines=lines,
    )
