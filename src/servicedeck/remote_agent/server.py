"""Protocol server loop for servicedeck-remote handling framed I/O over stdio."""

import asyncio
import getpass
import logging
import os
import socket

import servicedeck
from servicedeck.remote.models import (
    GoodbyeMessage,
    HelloMessage,
    RequestMessage,
)
from servicedeck.remote.protocol import read_message, write_message
from servicedeck.remote_agent.dispatcher import RequestDispatcher

logger = logging.getLogger(__name__)


class ProtocolServer:
    """Protocol server for the servicedeck-remote agent.

    Reads framed JSON requests from a StreamReader (stdin),
    dispatches them via RequestDispatcher, and writes framed JSON
    responses to a StreamWriter (stdout).
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
        await write_message(self._writer, hello)
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
                    logger.info("Received GoodbyeMessage (reason=%s). Shutting down.", message.reason)
                    break

                if isinstance(message, RequestMessage):
                    response = await self._dispatcher.dispatch(message)
                    await write_message(self._writer, response)
                else:
                    logger.warning("Unexpected message type ignored: %s", type(message).__name__)
        finally:
            self._running = False
            await self.shutdown()

    async def shutdown(self) -> None:
        """Gracefully terminate protocol session and close the writer."""
        logger.debug("Shutting down protocol server.")
        try:
            if not self._writer.is_closing():
                goodbye = GoodbyeMessage(reason="shutdown")
                await write_message(self._writer, goodbye)
                self._writer.close()
                await self._writer.wait_closed()
        except Exception as exc:
            logger.debug("Writer closure completed with: %s", exc)


__all__ = ["ProtocolServer"]
