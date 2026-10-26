"""API endpoints for managing remote host device configurations and connections."""

from fastapi import APIRouter, HTTPException, status

from servicedeck.backend.api.dependencies import RemoteManagerDep
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.schemas.remote import (
    RemoteConnectionResponse,
    RemoteDeviceCreateRequest,
    RemoteDeviceDisconnectResponse,
    RemoteDeviceResponse,
)

router = APIRouter(prefix="/remote/devices", tags=["Remote Devices"])


@router.get(
    "",
    response_model=list[RemoteDeviceResponse],
    summary="List Remote Devices",
    description="Retrieve all configured remote SSH devices and their live connection status.",
)
async def list_devices(remote_manager: RemoteManagerDep) -> list[RemoteDeviceResponse]:
    devices = remote_manager.list_devices()
    return [
        RemoteDeviceResponse(
            id=d.id,
            display_name=d.display_name,
            hostname=d.hostname,
            port=d.port,
            username=d.username,
            ssh_key_path=d.ssh_key_path,
            connected=remote_manager.is_connected(d.id),
        )
        for d in devices
    ]


@router.post(
    "",
    response_model=RemoteDeviceResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Add Remote Device",
    description="Save connection parameters for a new remote Linux host.",
)
async def add_device(
    payload: RemoteDeviceCreateRequest,
    remote_manager: RemoteManagerDep,
) -> RemoteDeviceResponse:
    device = RemoteDevice(
        id=payload.id,
        display_name=payload.display_name,
        hostname=payload.hostname,
        port=payload.port,
        username=payload.username,
        ssh_key_path=payload.ssh_key_path,
    )
    saved = remote_manager.add_device(device)
    return RemoteDeviceResponse(
        id=saved.id,
        display_name=saved.display_name,
        hostname=saved.hostname,
        port=saved.port,
        username=saved.username,
        ssh_key_path=saved.ssh_key_path,
        connected=remote_manager.is_connected(saved.id),
    )


@router.delete(
    "/{device_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Remove Remote Device",
    description="Disconnect and delete a remote device configuration.",
)
async def remove_device(device_id: str, remote_manager: RemoteManagerDep) -> None:
    removed = await remote_manager.remove_device(device_id)
    if not removed:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Device '{device_id}' not found.",
        )


@router.post(
    "/{device_id}/connect",
    response_model=RemoteConnectionResponse,
    summary="Connect to Remote Device",
    description="Establish an SSH transport session and start the remote agent process.",
)
async def connect_device(
    device_id: str,
    remote_manager: RemoteManagerDep,
) -> RemoteConnectionResponse:
    hello = await remote_manager.connect(device_id)
    return RemoteConnectionResponse(
        device_id=device_id,
        connected=True,
        remote_host=hello.host,
        remote_user=hello.user,
        remote_uid=hello.uid,
        remote_version=hello.servicedeck_version,
    )


@router.post(
    "/{device_id}/disconnect",
    response_model=RemoteDeviceDisconnectResponse,
    summary="Disconnect Remote Device",
    description="Terminate the SSH transport session to the specified device.",
)
async def disconnect_device(
    device_id: str,
    remote_manager: RemoteManagerDep,
) -> RemoteDeviceDisconnectResponse:
    await remote_manager.disconnect(device_id)
    return RemoteDeviceDisconnectResponse(device_id=device_id, connected=False)


@router.get(
    "/{device_id}/status",
    response_model=RemoteConnectionResponse,
    summary="Remote Device Connection Status",
    description="Query live connection state and agent handshake info.",
)
async def get_device_status(
    device_id: str,
    remote_manager: RemoteManagerDep,
) -> RemoteConnectionResponse:
    connected = remote_manager.is_connected(device_id)
    transport = remote_manager.connection_manager.get_transport(device_id)
    hello = transport.hello if transport else None

    return RemoteConnectionResponse(
        device_id=device_id,
        connected=connected,
        remote_host=hello.host if hello else None,
        remote_user=hello.user if hello else None,
        remote_uid=hello.uid if hello else None,
        remote_version=hello.servicedeck_version if hello else None,
    )
