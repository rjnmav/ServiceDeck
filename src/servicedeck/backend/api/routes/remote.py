"""API endpoints for executing systemd operations on remote Linux hosts via SSH."""

from typing import Annotated, Any

from fastapi import APIRouter, Query

from servicedeck.backend.api.dependencies import RemoteManagerDep
from servicedeck.backend.schemas.service import (
    CreateServiceRequest,
    CreateServiceResponse,
    DaemonReloadResponse,
    ResourceUsageResponse,
    ServiceLogsResponse,
    ServiceOperationResponse,
    ServiceResponse,
    UnitFileResponse,
)

router = APIRouter(prefix="/remote/{device_id}", tags=["Remote Services"])


@router.get(
    "/services",
    response_model=list[ServiceResponse],
    summary="List Remote Services",
    description="Retrieve all discovered systemd services from the specified remote device.",
)
async def list_remote_services(
    device_id: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> list[ServiceResponse]:
    services = await remote_manager.list_services(device_id=device_id, scope=scope)
    return [ServiceResponse.from_domain(svc) for svc in services]


@router.get(
    "/services/{service_name}",
    response_model=ServiceResponse,
    summary="Get Remote Service Details",
    description="Retrieve detailed status for a single systemd service on the remote device.",
)
async def get_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceResponse:
    service = await remote_manager.get_service(
        device_id=device_id,
        name=service_name,
        scope=scope,
    )
    return ServiceResponse.from_domain(service)


@router.post(
    "/services/{service_name}/start",
    response_model=ServiceOperationResponse,
    summary="Start Remote Service",
    description="Start a systemd service unit on the remote host.",
)
async def start_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.start_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="start",
        scope=scope or "default",
        message=f"Service '{service_name}' started successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/stop",
    response_model=ServiceOperationResponse,
    summary="Stop Remote Service",
    description="Stop a systemd service unit on the remote host.",
)
async def stop_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.stop_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="stop",
        scope=scope or "default",
        message=f"Service '{service_name}' stopped successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/restart",
    response_model=ServiceOperationResponse,
    summary="Restart Remote Service",
    description="Restart a systemd service unit on the remote host.",
)
async def restart_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.restart_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="restart",
        scope=scope or "default",
        message=f"Service '{service_name}' restarted successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/reload",
    response_model=ServiceOperationResponse,
    summary="Reload Remote Service",
    description="Reload configuration for a running service on the remote host.",
)
async def reload_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.reload_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="reload",
        scope=scope or "default",
        message=f"Service '{service_name}' reloaded successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/enable",
    response_model=ServiceOperationResponse,
    summary="Enable Remote Service",
    description="Enable a systemd service to start at boot on the remote host.",
)
async def enable_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.enable_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="enable",
        scope=scope or "default",
        message=f"Service '{service_name}' enabled successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/disable",
    response_model=ServiceOperationResponse,
    summary="Disable Remote Service",
    description="Disable a systemd service from starting at boot on the remote host.",
)
async def disable_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.disable_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="disable",
        scope=scope or "default",
        message=f"Service '{service_name}' disabled successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/mask",
    response_model=ServiceOperationResponse,
    summary="Mask Remote Service",
    description="Mask a service unit on the remote host.",
)
async def mask_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.mask_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="mask",
        scope=scope or "default",
        message=f"Service '{service_name}' masked successfully on '{device_id}'.",
    )


@router.post(
    "/services/{service_name}/unmask",
    response_model=ServiceOperationResponse,
    summary="Unmask Remote Service",
    description="Unmask a service unit on the remote host.",
)
async def unmask_remote_service(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceOperationResponse:
    await remote_manager.unmask_service(device_id=device_id, name=service_name, scope=scope)
    return ServiceOperationResponse(
        success=True,
        service=service_name,
        operation="unmask",
        scope=scope or "default",
        message=f"Service '{service_name}' unmasked successfully on '{device_id}'.",
    )


@router.post(
    "/daemon/reload",
    response_model=DaemonReloadResponse,
    summary="Reload Remote Daemon",
    description="Issue daemon-reload to systemd on the remote host.",
)
async def reload_remote_daemon(
    device_id: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> DaemonReloadResponse:
    await remote_manager.reload_daemon(device_id=device_id, scope=scope)
    return DaemonReloadResponse(
        success=True,
        scope=scope or "default",
        message=f"Systemd daemon configuration reloaded on '{device_id}'.",
    )


@router.get(
    "/services/{service_name}/unit-file",
    response_model=UnitFileResponse,
    summary="Get Remote Unit File",
    description="Retrieve the on-disk unit file content from the remote host.",
)
async def get_remote_unit_file(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> UnitFileResponse:
    path, content = await remote_manager.get_unit_file(
        device_id=device_id,
        name=service_name,
        scope=scope,
    )
    return UnitFileResponse(
        service=service_name,
        fragment_path=path,
        content=content,
        scope=scope or "default",
    )


@router.get(
    "/services/{service_name}/resources",
    response_model=ResourceUsageResponse,
    summary="Get Remote Service Resources",
    description="Retrieve live CPU, memory, and task statistics from the remote host.",
)
async def get_remote_resources(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ResourceUsageResponse:
    usage = await remote_manager.get_service_resources(
        device_id=device_id,
        name=service_name,
        scope=scope,
    )
    return ResourceUsageResponse(
        service=usage.service,
        cpu_usage_nsec=usage.cpu_usage_nsec,
        memory_current_bytes=usage.memory_current,
        disk_read_bytes=usage.io_read_bytes,
        disk_write_bytes=usage.io_write_bytes,
        tasks_current=usage.tasks_current,
        main_pid=usage.main_pid,
        active_enter_timestamp=usage.active_enter_timestamp_usec,
        active_state="active" if usage.is_active else "inactive",
        scope=usage.scope,
    )


@router.get(
    "/services/{service_name}/logs",
    response_model=ServiceLogsResponse,
    summary="Get Remote Service Logs",
    description="Retrieve recent journal logs for a service unit from the remote host.",
)
async def get_remote_logs(
    device_id: str,
    service_name: str,
    remote_manager: RemoteManagerDep,
    lines: Annotated[int, Query(ge=1, le=5000, description="Log lines to retrieve")] = 200,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> ServiceLogsResponse:
    logs = await remote_manager.get_service_logs(
        device_id=device_id,
        name=service_name,
        lines=lines,
        scope=scope,
    )
    return ServiceLogsResponse(
        service=service_name,
        logs=logs,
        scope=scope or "default",
        lines=lines,
    )


@router.post(
    "/services/create",
    response_model=CreateServiceResponse,
    summary="Create Remote Service Unit",
    description="Install a new systemd unit file on the remote host.",
)
async def create_remote_service(
    device_id: str,
    request: CreateServiceRequest,
    remote_manager: RemoteManagerDep,
) -> CreateServiceResponse:
    path = await remote_manager.create_service(
        device_id=device_id,
        name=request.name,
        content=request.content,
        scope=request.scope,
        overwrite=request.overwrite,
    )
    return CreateServiceResponse(
        success=True,
        service=request.name,
        path=path,
        scope=request.scope or "user",
    )


@router.get(
    "/health",
    summary="Remote Host Systemd Health",
    description="Check remote systemd D-Bus interface health.",
)
async def check_remote_health(
    device_id: str,
    remote_manager: RemoteManagerDep,
    scope: Annotated[str | None, Query(description="Scope ('user' or 'system')")] = None,
) -> dict[str, Any]:
    healthy = await remote_manager.is_healthy(device_id=device_id, scope=scope)
    return {
        "device_id": device_id,
        "healthy": healthy,
        "scope": scope or "default",
    }
