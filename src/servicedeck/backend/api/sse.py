"""Server-Sent Events plumbing for the live streaming endpoints.

Every stream is an async iterator from the core layer whose first item means "set up".
Routes await that first item *before* building the response (:func:`prime`), so a failure
to start (unknown service, remote host unreachable, elevation needed) still goes through
the normal exception handlers and becomes a proper HTTP error status.

Wire format (``text/event-stream``)::

    event: <name>
    data: <json>

The last event of every stream is ``end`` (it finished) or ``error`` with
``{"error": <type>, "message": <text>}``. A ``: keepalive`` comment is sent while idle so
dead clients are noticed and clients can use a read timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import AsyncIterator, Callable, Iterable
from typing import Any

from fastapi.responses import StreamingResponse

from servicedeck.backend.exceptions import ServiceDeckError
from servicedeck.backend.models.service import ServiceEvent
from servicedeck.backend.schemas.service import ServiceResponse

logger = logging.getLogger(__name__)

#: Seconds between keepalive comments on an idle stream.
KEEPALIVE_SECONDS = 15.0

SSEItem = tuple[str, Any]

_DONE = object()


def format_sse(event: str, data: Any) -> str:
    """Encode one Server-Sent Event."""
    return f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


def error_payload(exc: BaseException) -> dict[str, Any]:
    """The ``error`` event body for an exception (never includes a traceback)."""
    message = exc.message if isinstance(exc, ServiceDeckError) else str(exc)
    return {"error": type(exc).__name__, "message": message}


async def prime[T](source: AsyncIterator[T]) -> T:
    """Start ``source`` and return its first ("ready") item; errors propagate to handlers."""
    try:
        return await anext(source)
    except StopAsyncIteration:
        raise ServiceDeckError("The stream ended before it started.") from None


async def _sse_body[T](
    source: AsyncIterator[T],
    encode: Callable[[T], SSEItem | None],
    initial: Iterable[SSEItem],
    keepalive: float,
) -> AsyncIterator[str]:
    for event, data in initial:
        yield format_sse(event, data)

    # A pump task reads the source so that waiting for the next item can time out (for
    # keepalives) without cancelling the source itself.
    queue: asyncio.Queue[Any] = asyncio.Queue()

    async def pump() -> None:
        try:
            async for item in source:
                encoded = encode(item)
                if encoded is not None:
                    queue.put_nowait(encoded)
            queue.put_nowait(("end", None))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Event stream ended with an error: %s", exc)
            queue.put_nowait(("error", error_payload(exc)))
        finally:
            with contextlib.suppress(Exception):
                await source.aclose()  # type: ignore[attr-defined]
            queue.put_nowait(_DONE)

    task = asyncio.create_task(pump(), name="servicedeck-sse-pump")
    try:
        while True:
            try:
                item = await asyncio.wait_for(queue.get(), timeout=keepalive)
            except TimeoutError:
                yield ": keepalive\n\n"
                continue
            if item is _DONE:
                return
            yield format_sse(*item)
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task


def sse_response[T](
    source: AsyncIterator[T],
    encode: Callable[[T], SSEItem | None],
    *,
    initial: Iterable[SSEItem] = (),
    keepalive: float = KEEPALIVE_SECONDS,
) -> StreamingResponse:
    """Stream ``source`` as Server-Sent Events, after the already-encoded ``initial`` ones."""
    return StreamingResponse(
        _sse_body(source, encode, list(initial), keepalive),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def encode_service_event(event: ServiceEvent) -> SSEItem | None:
    """SSE form of a :class:`ServiceEvent`."""
    if event.kind == "changed" and event.service is not None:
        return "service", ServiceResponse.from_domain(event.service).model_dump()
    if event.kind == "removed":
        return "removed", {"name": event.name, "scope": event.scope}
    if event.kind in ("ready", "resync"):
        return event.kind, {"scope": event.scope}
    return None


def encode_log_line(line: str) -> SSEItem:
    return "log", {"line": line}


async def service_events_response(events: AsyncIterator[ServiceEvent]) -> StreamingResponse:
    """Prime a service watch and stream it; the first event sent is ``ready``."""
    first = await prime(events)
    encoded = encode_service_event(first)
    return sse_response(events, encode_service_event, initial=[encoded] if encoded else [])


async def log_lines_response(
    lines: AsyncIterator[str], *, service: str, scope: str | None
) -> StreamingResponse:
    """Prime a log follow and stream it; the first event sent is ``ready``."""
    await prime(lines)
    return sse_response(
        lines, encode_log_line, initial=[("ready", {"service": service, "scope": scope})]
    )


__all__ = [
    "KEEPALIVE_SECONDS",
    "encode_service_event",
    "error_payload",
    "format_sse",
    "log_lines_response",
    "prime",
    "service_events_response",
    "sse_response",
]
