"""Low-level helpers shared by every agent channel (normal and privileged).

An agent channel is one SSH exec process running the remote agent; requests and responses
are framed messages on its stdin/stdout, and its stderr carries the agent's log output.

After the handshake, :class:`AgentChannel` owns the channel's stdout: one reader task
matches responses to requests by id and routes ``event`` messages to open streams, so a
long-lived stream (live updates, ``journalctl -f``) shares the channel with normal calls.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
from collections.abc import AsyncIterator
from typing import Any

from servicedeck.backend.exceptions import RemoteConnectionError
from servicedeck.remote.exceptions import RemoteTimeoutError
from servicedeck.remote.models import (
    CancelMessage,
    EventMessage,
    GoodbyeMessage,
    ProtocolMessage,
    RequestMessage,
    ResponseMessage,
)
from servicedeck.remote.protocol import read_message, write_message

logger = logging.getLogger(__name__)
#: Receives the remote agent's stderr, line by line.
agent_logger = logging.getLogger("servicedeck.remote.agent")


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


class _StreamEnd:
    """Queue sentinel: the stream is over (optionally with an error)."""

    def __init__(self, error: BaseException | None = None, data: Any = None) -> None:
        self.error = error
        self.data = data


class RemoteStream:
    """Events of one agent stream, consumed with ``async for event, data in stream``.

    Iteration stops after the agent's ``end`` event, which is yielded as the final
    ``("end", data)`` pair so the caller can inspect an error it carries. If the channel
    breaks first, iteration raises ``RemoteConnectionError``.
    """

    def __init__(self, channel: AgentChannel, stream_id: int) -> None:
        self._channel = channel
        self.stream_id = stream_id
        self._queue: asyncio.Queue[tuple[str, Any] | _StreamEnd] = asyncio.Queue()
        self._done = False

    def _put(self, item: tuple[str, Any] | _StreamEnd) -> None:
        self._queue.put_nowait(item)

    def __aiter__(self) -> AsyncIterator[tuple[str, Any]]:
        return self

    async def __anext__(self) -> tuple[str, Any]:
        if self._done:
            raise StopAsyncIteration
        item = await self._queue.get()
        if isinstance(item, _StreamEnd):
            self._done = True
            self._channel._forget_stream(self.stream_id)
            if item.error is not None:
                raise item.error
            return "end", item.data
        return item

    async def aclose(self) -> None:
        """Stop the stream; tells the agent to cancel it if it is still running."""
        if self._done:
            return
        self._done = True
        await self._channel._cancel_stream(self.stream_id)


class AgentChannel:
    """Multiplexes requests and streams over one agent process's stdin/stdout."""

    def __init__(self, process: Any, host: str, label: str) -> None:
        self.process = process
        self._host = host
        self._label = label
        self._pending: dict[int, asyncio.Future[ResponseMessage]] = {}
        self._streams: dict[int, RemoteStream] = {}
        self._write_lock = asyncio.Lock()
        self._closed_error: RemoteConnectionError | None = None
        self._reader = asyncio.create_task(self._read_loop(), name=f"servicedeck-reader-{label}")

    @property
    def closed(self) -> bool:
        return self._closed_error is not None

    def _disconnected_error(self) -> RemoteConnectionError:
        return RemoteConnectionError(
            f"Remote agent on {self._host} disconnected unexpectedly",
            details={"host": self._host},
        )

    async def _read_loop(self) -> None:
        error: RemoteConnectionError | None = None
        try:
            while True:
                message = await read_message(self.process.stdout)
                if message is None or isinstance(message, GoodbyeMessage):
                    break
                if isinstance(message, ResponseMessage):
                    future = self._pending.pop(message.id, None)
                    if future is not None and not future.done():
                        future.set_result(message)
                    else:
                        logger.debug(
                            "[%s] Dropping unsolicited response %d", self._label, message.id
                        )
                elif isinstance(message, EventMessage):
                    stream = self._streams.get(message.stream)
                    if stream is None:
                        continue
                    if message.event == "end":
                        stream._put(_StreamEnd(data=message.data))
                    else:
                        stream._put((message.event, message.data))
                else:
                    logger.debug("[%s] Ignoring %s", self._label, type(message).__name__)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[%s] Agent channel read failed: %s", self._label, exc)
            error = RemoteConnectionError(
                f"Lost the connection to the agent on {self._host}: {exc}",
                details={"host": self._host},
            )
        finally:
            self._fail_all(error or self._disconnected_error())

    def _fail_all(self, error: RemoteConnectionError) -> None:
        if self._closed_error is None:
            self._closed_error = error
        for future in self._pending.values():
            if not future.done():
                future.set_exception(error)
        self._pending.clear()
        for stream in self._streams.values():
            stream._put(_StreamEnd(error=error))
        self._streams.clear()

    async def _write(self, message: ProtocolMessage) -> None:
        async with self._write_lock:
            await write_message(self.process.stdin, message)

    async def request(self, request: RequestMessage, timeout: float) -> ResponseMessage:
        """Send ``request`` and wait for the response with the same id."""
        if self._closed_error is not None:
            raise self._disconnected_error()
        future: asyncio.Future[ResponseMessage] = asyncio.get_running_loop().create_future()
        self._pending[request.id] = future
        try:
            try:
                await self._write(request)
            except Exception as exc:
                logger.error("Failed to write request %d to remote agent: %s", request.id, exc)
                raise RemoteConnectionError(
                    f"Failed to transmit request {request.id} to {self._host}: {exc}",
                    details={"request_id": request.id},
                ) from exc
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=timeout)
            except TimeoutError as exc:
                raise RemoteTimeoutError(
                    request_id=request.id, method=request.method, timeout_seconds=timeout
                ) from exc
        finally:
            self._pending.pop(request.id, None)

    async def open_stream(
        self, request: RequestMessage, timeout: float
    ) -> tuple[ResponseMessage, RemoteStream | None]:
        """Send a ``stream.*`` request; returns its response and, on success, the stream.

        The stream is registered before the request is written, so no early event is lost.
        """
        stream = RemoteStream(self, request.id)
        self._streams[request.id] = stream
        try:
            response = await self.request(request, timeout)
        except BaseException:
            self._streams.pop(request.id, None)
            raise
        if not response.success:
            self._streams.pop(request.id, None)
            return response, None
        return response, stream

    def _forget_stream(self, stream_id: int) -> None:
        self._streams.pop(stream_id, None)

    async def _cancel_stream(self, stream_id: int) -> None:
        if self._streams.pop(stream_id, None) is None or self.closed:
            return
        with contextlib.suppress(Exception):
            await self._write(CancelMessage(stream=stream_id))

    async def close(self) -> None:
        """Stop reading; pending requests and open streams fail. Safe to call repeatedly."""
        if not self._reader.done():
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._reader
        self._fail_all(self._disconnected_error())


__all__ = [
    "AgentChannel",
    "RemoteStream",
    "agent_logger",
    "drain_stderr",
]
