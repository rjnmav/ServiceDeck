"""Live service-change stream for the local machine (Server-Sent Events)."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from servicedeck.backend.api.dependencies import get_service_manager
from servicedeck.backend.api.sse import service_events_response
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.models.service import ServiceScope

router = APIRouter(tags=["events"])

ServiceManagerDep = Annotated[ServiceManager, Depends(get_service_manager)]


@router.get(
    "/events",
    summary="Stream service changes",
    description=(
        "Server-Sent Events stream of live service changes for the scope. Events: `ready` "
        "(watching; list services now), `service` (a service's new state), `removed` "
        "(`{name, scope}`), `resync` (bulk change such as daemon-reload: re-list), and a "
        "final `end` or `error`."
    ),
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
async def stream_service_events(
    service_manager: ServiceManagerDep,
    scope: Annotated[
        ServiceScope | None,
        Query(description="Scope to watch ('user' or 'system'); defaults to the active scope"),
    ] = None,
) -> StreamingResponse:
    resolved_scope = service_manager.resolve_scope(scope)
    return await service_events_response(service_manager.watch_services(scope=resolved_scope))
