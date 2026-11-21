"""API endpoints for managing remote host device configurations and connections."""

from fastapi import APIRouter, HTTPException, status

from servicedeck.backend.api.dependencies import RemoteManagerDep
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.known_hosts import HostKeyInfo
from servicedeck.backend.schemas.remote import (
    HostKeyResponse,
    RemoteConnectionResponse,
    RemoteDeviceCreateRequest,
    RemoteDeviceDisconnectResponse,
    RemoteDeviceResponse,
    SetupKeyRequest,
    SetupKeyResponse,
    TrustHostKeyRequest,
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
            agent_mode=d.agent_mode,  # type: ignore[arg-type]
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
        agent_mode=payload.agent_mode,
    )
    saved = remote_manager.add_device(device)
    return RemoteDeviceResponse(
        id=saved.id,
        display_name=saved.display_name,
        hostname=saved.hostname,
        port=saved.port,
        username=saved.username,
        ssh_key_path=saved.ssh_key_path,
        agent_mode=saved.agent_mode,  # type: ignore[arg-type]
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


def _host_key_response(info: HostKeyInfo) -> HostKeyResponse:
    return HostKeyResponse(
        hostname=info.hostname,
        port=info.port,
        status=info.status,
        key_type=info.key_type,
        fingerprint=info.fingerprint,
    )


@router.get(
    "/{device_id}/host-key",
    response_model=HostKeyResponse,
    summary="Inspect Remote Host Key",
    description="Fetch the device's SSH host key fingerprint and whether it is already trusted.",
)
async def get_host_key(device_id: str, remote_manager: RemoteManagerDep) -> HostKeyResponse:
    return _host_key_response(await remote_manager.check_host_key(device_id))


@router.post(
    "/{device_id}/host-key/trust",
    response_model=HostKeyResponse,
    summary="Trust Remote Host Key",
    description="Record the device's SSH host key after the user verified its fingerprint. "
    "Refused if the key no longer matches the confirmed fingerprint, or if a different key "
    "is already trusted for this host.",
)
async def trust_host_key(
    device_id: str,
    payload: TrustHostKeyRequest,
    remote_manager: RemoteManagerDep,
) -> HostKeyResponse:
    return _host_key_response(await remote_manager.trust_host_key(device_id, payload.fingerprint))


@router.post(
    "/{device_id}/setup-key",
    response_model=SetupKeyResponse,
    summary="Set Up SSH Key Login",
    description="Log in once with the remote account password, install the ServiceDeck SSH "
    "key in ~/.ssh/authorized_keys and verify that key login works. The password is used for "
    "that single login and is never stored or logged.",
)
async def setup_key(
    device_id: str,
    payload: SetupKeyRequest,
    remote_manager: RemoteManagerDep,
) -> SetupKeyResponse:
    result = await remote_manager.setup_key(device_id, payload.password.get_secret_value())
    device = result.device
    return SetupKeyResponse(
        device=RemoteDeviceResponse(
            id=device.id,
            display_name=device.display_name,
            hostname=device.hostname,
            port=device.port,
            username=device.username,
            ssh_key_path=device.ssh_key_path,
            agent_mode=device.agent_mode,  # type: ignore[arg-type]
            connected=remote_manager.is_connected(device.id),
        ),
        key_path=str(result.key.private_path),
        key_fingerprint=result.key.fingerprint,
        added=result.added,
    )
