"""Protocol server loop for servicedeck-remote handling framed I/O over stdio."""

import asyncio
import contextlib
import getpass
import logging
import os
import socket
from typing import Any

import servicedeck
from servicedeck.remote.models import (
    CancelMessage,
    EventMessage,
    GoodbyeMessage,
    HelloMessage,
    ProtocolMessage,
    RequestMessage,
    success_response,
)
from servicedeck.remote.protocol import read_message, write_message
from servicedeck.remote_agent.dispatcher import RequestDispatcher

logger = logging.getLogger(__name__)


class ProtocolServer:
    """Protocol server for the servicedeck-remote agent.

    Reads framed JSON requests from a StreamReader (stdin),
    dispatches them via RequestDispatcher, and writes framed JSON
    responses to a StreamWriter (stdout).

    ``stream.*`` requests are answered at once with ``{"stream": <request id>}`` and then
    run as background tasks that send ``event`` messages until they end or the client
    sends ``cancel``. Ordinary requests keep being served meanwhile.
    """

    def __init__(
        self,
        dispatcher: RequestDispatcher,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self._dispatcher = dispatcher
        self._reader = reader
        self._writer = writer
        self._running = False
        self._streams: dict[int, asyncio.Task[None]] = {}
        self._write_lock = asyncio.Lock()

    async def _send(self, message: ProtocolMessage) -> None:
        async with self._write_lock:
            await write_message(self._writer, message)

    async def send_hello(self) -> None:
        """Send the initial handshake HelloMessage with host and environment details."""
        hostname = socket.gethostname()
        username = getpass.getuser()
        uid = os.getuid()
        version = getattr(servicedeck, "__version__", "2.0.0")

        hello = HelloMessage(
            host=hostname,
            user=username,
            uid=uid,
            servicedeck_version=version,
        )
        await self._send(hello)
        logger.debug("Sent HelloMessage: host=%s, user=%s, uid=%d", hostname, username, uid)

    async def run(self) -> None:
        """Main protocol loop.

        Sends initial hello, then reads messages from reader, dispatches requests,
        and writes responses until EOF or GoodbyeMessage is received.
        """
        self._running = True
        try:
            await self.send_hello()

            while self._running:
                try:
                    message = await read_message(self._reader)
                except Exception as exc:
                    logger.error("Error reading framed message: %s", exc)
                    break

                if message is None:
                    logger.info("EOF reached on input stream. Remote client disconnected.")
                    break

                if isinstance(message, GoodbyeMessage):
                    logger.info(
                        "Received GoodbyeMessage (reason=%s). Shutting down.", message.reason
                    )
                    break

                if isinstance(message, RequestMessage):
                    if self._dispatcher.is_stream_method(message.method):
                        await self._open_stream(message)
                    else:
                        response = await self._dispatcher.dispatch(message)
                        await self._send(response)
                elif isinstance(message, CancelMessage):
                    await self._cancel_stream(message.stream)
                else:
                    logger.warning("Unexpected message type ignored: %s", type(message).__name__)
        finally:
            self._running = False
            await self.shutdown()

    async def _open_stream(self, request: RequestMessage) -> None:
        """Start a stream, answer the request, then pump its events in the background."""
        stream_id = request.id
        try:
            if stream_id in self._streams:
                raise ValueError(f"Stream {stream_id} is already open")
            stream = self._dispatcher.open_stream(request.method, request.params or {})
            await anext(stream)  # the "ready" item: setup succeeded
        except Exception as exc:
            await self._send(self._dispatcher.error_response_for(request.id, exc))
            return

        await self._send(success_response(request.id, {"stream": stream_id}))
        self._streams[stream_id] = asyncio.create_task(
            self._pump_stream(stream_id, stream), name=f"servicedeck-stream-{stream_id}"
        )

    async def _pump_stream(self, stream_id: int, stream: Any) -> None:
        end: dict[str, Any] | None = None
        try:
            async for event, data in stream:
                await self._send(EventMessage(stream=stream_id, event=event, data=data))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.info("Stream %d ended with an error: %s", stream_id, exc)
            error = self._dispatcher.error_response_for(stream_id, exc).error
            end = (
                {"error": {"code": error.code, "message": error.message, "details": error.details}}
                if error
                else None
            )
        finally:
            with contextlib.suppress(Exception):
                await stream.aclose()
            self._streams.pop(stream_id, None)
        with contextlib.suppress(Exception):
            await self._send(EventMessage(stream=stream_id, event="end", data=end))

    async def _cancel_stream(self, stream_id: int) -> None:
        task = self._streams.pop(stream_id, None)
        if task is None:
            return
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        with contextlib.suppress(Exception):
            await self._send(EventMessage(stream=stream_id, event="end", data=None))

    async def _cancel_all_streams(self) -> None:
        for stream_id in list(self._streams):
            task = self._streams.pop(stream_id)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def shutdown(self) -> None:
        """Gracefully terminate protocol session and close the writer."""
        logger.debug("Shutting down protocol server.")
        await self._cancel_all_streams()
        try:
            if not self._writer.is_closing():
                goodbye = GoodbyeMessage(reason="shutdown")
                await self._send(goodbye)
                self._writer.close()
                await self._writer.wait_closed()
        except Exception as exc:
            logger.debug("Writer closure completed with: %s", exc)


__all__ = ["ProtocolServer"]
