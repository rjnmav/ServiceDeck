"""Administrator access on this computer, for system-scope unit file changes.

Mirrors ``/api/remote/devices/{id}/elevate`` for the local machine: a root agent is started
with sudo once, and system unit files are created, edited and reverted through it.
"""

from fastapi import APIRouter, status

from servicedeck.backend.api.dependencies import LocalAdminDep
from servicedeck.backend.schemas.remote import ElevateRequest
from servicedeck.backend.schemas.service import ElevationStatusResponse

router = APIRouter(prefix="/elevation", tags=["elevation"])


def _status(local_admin: LocalAdminDep) -> ElevationStatusResponse:
    return ElevationStatusResponse(
        elevated=local_admin.is_elevated, idle_timeout=local_admin.idle_timeout
    )


@router.get(
    "",
    response_model=ElevationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Local administrator access status",
)
async def get_elevation(local_admin: LocalAdminDep) -> ElevationStatusResponse:
    return _status(local_admin)


@router.post(
    "",
    response_model=ElevationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Get administrator access on this computer",
    description="Start a local root agent through sudo so system unit files can be created "
    "and edited. The password answers sudo once and is never stored or logged; omit it to "
    "try passwordless sudo.",
)
async def elevate(payload: ElevateRequest, local_admin: LocalAdminDep) -> ElevationStatusResponse:
    password = payload.password.get_secret_value() if payload.password is not None else None
    await local_admin.elevate(password)
    del password
    return _status(local_admin)


@router.delete(
    "",
    response_model=ElevationStatusResponse,
    status_code=status.HTTP_200_OK,
    summary="Drop administrator access on this computer",
)
async def drop_elevation(local_admin: LocalAdminDep) -> ElevationStatusResponse:
    await local_admin.drop()
    return _status(local_admin)
