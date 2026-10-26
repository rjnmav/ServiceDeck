"""SSH transport implementation utilizing asyncssh for remote agent communication."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import asyncssh

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    SSHAuthenticationError,
)
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.remote.exceptions import RemoteProtocolError, RemoteTimeoutError
from servicedeck.remote.models import (
    GoodbyeMessage,
    HelloMessage,
    RequestMessage,
    ResponseMessage,
)
from servicedeck.remote.protocol import ProtocolEncoder, read_message, write_message

logger = logging.getLogger(__name__)


class SSHTransport:
    """Manages an SSH connection to a remote host and executes servicedeck-remote over stdio.

    Translates asyncssh exceptions into structured ServiceDeck domain exceptions.
    Encapsulates all asyncssh imports and low-level channel handling.
    """

    def __init__(
        self,
        device: RemoteDevice,
        remote_command: str = "servicedeck-remote",
    ) -> None:
        self._device = device
        self._remote_command = remote_command
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._hello: HelloMessage | None = None
        self._encoder = ProtocolEncoder()

    @property
    def device(self) -> RemoteDevice:
        """Return the target remote device configuration."""
        return self._device

    @property
    def is_connected(self) -> bool:
        """Return True if both the SSH connection and remote agent process are active."""
        if self._conn is None or self._process is None:
            return False
        return not self._process.is_closing()

    @property
    def hello(self) -> HelloMessage | None:
        """Return the handshake HelloMessage received from the remote agent."""
        return self._hello

    async def connect(self, timeout: float = 15.0) -> HelloMessage:
        """Establish SSH connection, spawn servicedeck-remote, and await Hello handshake."""
        logger.info(
            "Connecting to %s (%s:%d as %s)",
            self._device.display_name,
            self._device.hostname,
            self._device.port,
            self._device.username or "default user",
        )

        connect_kwargs: dict[str, Any] = {
            "host": self._device.hostname,
            "port": self._device.port,
            "username": self._device.username,
            "agent_forwarding": False,
        }
        if self._device.ssh_key_path:
            connect_kwargs["client_keys"] = [self._device.ssh_key_path]

        try:
            self._conn = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=timeout,
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            msg = f"SSH host key verification failed for {self._device.hostname}: {exc}"
            logger.error(msg)
            raise RemoteHostKeyChangedError(msg, details={"hostname": self._device.hostname}) from exc
        except asyncssh.PermissionDenied as exc:
            msg = f"SSH authentication failed for {self._device.hostname}: {exc}"
            logger.error(msg)
            raise SSHAuthenticationError(msg, details={"hostname": self._device.hostname}) from exc
        except TimeoutError as exc:
            msg = f"Connection timeout after {timeout}s to {self._device.hostname}:{self._device.port}"
            logger.error(msg)
            raise RemoteConnectionError(msg, details={"hostname": self._device.hostname}) from exc
        except (asyncssh.Error, OSError) as exc:
            msg = f"SSH connection failed to {self._device.hostname}:{self._device.port}: {exc}"
            logger.error(msg)
            raise RemoteConnectionError(msg, details={"hostname": self._device.hostname}) from exc

        try:
            logger.debug("Spawning remote process: %s", self._remote_command)
            self._process = await self._conn.create_process(
                self._remote_command,
                stdin=asyncssh.PIPE,
                stdout=asyncssh.PIPE,
                stderr=asyncssh.PIPE,
                encoding=None,
            )
        except (asyncssh.Error, OSError) as exc:
            await self.disconnect()
            msg = f"Failed to execute '{self._remote_command}' on {self._device.hostname}: {exc}"
            logger.error(msg)
            raise RemoteConnectionError(msg, details={"command": self._remote_command}) from exc

        try:
            # Wait for the handshake HelloMessage from the agent
            message = await asyncio.wait_for(
                read_message(self._process.stdout),  # type: ignore[arg-type]
                timeout=timeout,
            )
            if not isinstance(message, HelloMessage):
                await self.disconnect()
                raise RemoteProtocolError(
                    f"Expected HelloMessage on startup, received {type(message).__name__ if message else 'EOF'}",
                    details={"received": str(message)},
                )

            self._hello = message
            logger.info(
                "Handshake established with %s (remote user: %s, uid: %d, version: %s)",
                self._device.hostname,
                message.user,
                message.uid,
                message.servicedeck_version,
            )
            return self._hello
        except TimeoutError as exc:
            await self.disconnect()
            raise RemoteTimeoutError(
                request_id=0,
                method="hello",
                timeout_seconds=timeout,
            ) from exc
        except Exception:
            await self.disconnect()
            raise

    async def send_request(
        self,
        request: RequestMessage,
        timeout: float = 30.0,
    ) -> ResponseMessage:
        """Send a RequestMessage to the remote agent and await a correlating ResponseMessage."""
        if not self.is_connected or self._process is None:
            raise RemoteConnectionError(
                f"Cannot send request {request.id}: connection to {self._device.hostname} is not open",
                details={"request_id": request.id, "device_id": self._device.id},
            )

        try:
            await write_message(self._process.stdin, request)  # type: ignore[arg-type]
        except Exception as exc:
            logger.error("Failed to write request %d to remote agent: %s", request.id, exc)
            raise RemoteConnectionError(
                f"Failed to transmit request {request.id} to {self._device.hostname}: {exc}",
                details={"request_id": request.id},
            ) from exc

        try:
            response = await asyncio.wait_for(
                read_message(self._process.stdout),  # type: ignore[arg-type]
                timeout=timeout,
            )
        except TimeoutError as exc:
            raise RemoteTimeoutError(
                request_id=request.id,
                method=request.method,
                timeout_seconds=timeout,
            ) from exc

        if response is None:
            raise RemoteConnectionError(
                f"Remote agent on {self._device.hostname} disconnected unexpectedly while awaiting response to request {request.id}",
                details={"request_id": request.id},
            )

        if not isinstance(response, ResponseMessage):
            raise RemoteProtocolError(
                f"Unexpected message type received in reply to request {request.id}: {type(response).__name__}",
                details={"received_type": type(response).__name__},
            )

        return response

    async def disconnect(self) -> None:
        """Gracefully terminate agent session and close SSH connection."""
        logger.info("Disconnecting from %s (%s)", self._device.display_name, self._device.hostname)

        if self._process is not None and not self._process.is_closing():
            try:
                goodbye = GoodbyeMessage(reason="disconnect")
                await write_message(self._process.stdin, goodbye)  # type: ignore[arg-type]
                self._process.stdin.close()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except Exception as exc:
                logger.debug("Process termination finished with: %s", exc)
                try:
                    self._process.terminate()
                except Exception:
                    pass

        if self._conn is not None:
            try:
                self._conn.close()
                await self._conn.wait_closed()
            except Exception as exc:
                logger.debug("SSH connection closure finished with: %s", exc)

        self._process = None
        self._conn = None
        self._hello = None


__all__ = ["SSHTransport"]
