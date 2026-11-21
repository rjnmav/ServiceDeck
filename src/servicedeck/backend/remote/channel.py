"""Low-level helpers shared by every agent channel (normal and privileged).

An agent channel is one SSH exec process running the remote agent; requests and responses
are framed messages on its stdin/stdout, and its stderr carries the agent's log output.
"""

from __future__ import annotations

import asyncio
import collections
import logging
from typing import Any

from servicedeck.backend.exceptions import RemoteConnectionError
from servicedeck.remote.exceptions import RemoteProtocolError, RemoteTimeoutError
from servicedeck.remote.models import RequestMessage, ResponseMessage
from servicedeck.remote.protocol import read_message, write_message

logger = logging.getLogger(__name__)
#: Receives the remote agent's stderr, line by line.
agent_logger = logging.getLogger("servicedeck.remote.agent")


async def exchange_request(
    process: Any, request: RequestMessage, timeout: float, host: str
) -> ResponseMessage:
    """Write ``request`` to the agent and read its response.

    Raises on any failure; the caller must tear the channel down, because a half-written
    request or an unread response leaves the stream out of sync.
    """
    try:
        await write_message(process.stdin, request)
    except Exception as exc:
        logger.error("Failed to write request %d to remote agent: %s", request.id, exc)
        raise RemoteConnectionError(
            f"Failed to transmit request {request.id} to {host}: {exc}",
            details={"request_id": request.id},
        ) from exc

    try:
        response = await asyncio.wait_for(read_message(process.stdout), timeout=timeout)
    except TimeoutError as exc:
        raise RemoteTimeoutError(
            request_id=request.id, method=request.method, timeout_seconds=timeout
        ) from exc
    except Exception as exc:
        raise RemoteConnectionError(
            f"Failed to read response to request {request.id} from {host}: {exc}",
            details={"request_id": request.id},
        ) from exc

    if response is None:
        raise RemoteConnectionError(
            f"Remote agent on {host} disconnected unexpectedly while awaiting response "
            f"to request {request.id}",
            details={"request_id": request.id},
        )
    if not isinstance(response, ResponseMessage):
        raise RemoteProtocolError(
            f"Unexpected message type received in reply to request {request.id}: "
            f"{type(response).__name__}",
            details={"received_type": type(response).__name__},
        )
    return response


async def drain_stderr(stream: Any, label: str, tail: collections.deque[str]) -> None:
    """Read remote stderr until EOF so the SSH window never fills and blocks the agent."""
    try:
        while True:
            line = await stream.readline()
            if not line:
                return
            text = line.decode("utf-8", errors="replace").rstrip()
            if not text:
                continue
            tail.append(text)
            level = (
                logging.WARNING
                if any(tag in text for tag in ("[ERROR]", "[CRITICAL]", "Traceback"))
                else logging.DEBUG
            )
            agent_logger.log(level, "[%s] %s", label, text)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("Stopped reading remote stderr for %s: %s", label, exc)


__all__ = ["agent_logger", "drain_stderr", "exchange_request"]
