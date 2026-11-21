"""SSH transport implementation utilizing asyncssh for remote agent communication."""

from __future__ import annotations

import asyncio
import collections
import logging
import shlex
from typing import Any

import asyncssh

from servicedeck.backend.exceptions import (
    RemoteAgentBootstrapError,
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    SSHAuthenticationError,
)
from servicedeck.backend.remote.bundle import (
    PYTHON_TOO_OLD_MARKER,
    AgentPayload,
    get_agent_payload,
    stage1_command,
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
#: Receives the remote agent's stderr, line by line.
agent_logger = logging.getLogger("servicedeck.remote.agent")

_STDERR_TAIL_LINES = 20


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
        self._lock = asyncio.Lock()
        self._launch_mode: str | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=_STDERR_TAIL_LINES)

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
        """Establish SSH connection, start the remote agent, and await the Hello handshake.

        With ``agent_mode="bundled"`` the agent is streamed over the SSH channel and run
        from memory, so nothing has to be installed on the remote host.
        """
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
            raise RemoteHostKeyChangedError(
                msg, details={"hostname": self._device.hostname}
            ) from exc
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

        command, payload, mode = await self._resolve_launch()
        self._launch_mode = mode

        try:
            logger.debug("Spawning remote agent on %s (mode=%s)", self._device.hostname, mode)
            self._process = await self._conn.create_process(
                command,
                stdin=asyncssh.PIPE,
                stdout=asyncssh.PIPE,
                stderr=asyncssh.PIPE,
                encoding=None,
            )
        except (asyncssh.Error, OSError) as exc:
            await self.disconnect()
            msg = f"Failed to start remote agent on {self._device.hostname}: {exc}"
            logger.error(msg)
            raise RemoteConnectionError(msg, details={"mode": mode}) from exc

        self._start_stderr_drain()

        if payload is not None:
            try:
                logger.debug(
                    "Sending bundled agent to %s (%d bytes, sha256=%s)",
                    self._device.hostname,
                    len(payload.data),
                    payload.sha256[:12],
                )
                self._process.stdin.write(payload.data)
                await self._process.stdin.drain()
            except Exception as exc:
                raise await self._bootstrap_failure(f"failed to send agent bundle: {exc}") from exc

        try:
            # Wait for the handshake HelloMessage from the agent
            message = await asyncio.wait_for(
                read_message(self._process.stdout),  # type: ignore[arg-type]
                timeout=timeout,
            )
            if message is None:
                raise await self._bootstrap_failure("agent exited before the handshake")
            if not isinstance(message, HelloMessage):
                await self.disconnect()
                raise RemoteProtocolError(
                    f"Expected HelloMessage on startup, received {type(message).__name__}",
                    details={"received": str(message)},
                )

            self._hello = message
            logger.info(
                "Handshake established with %s (remote user: %s, uid: %d, version: %s, mode: %s)",
                self._device.hostname,
                message.user,
                message.uid,
                message.servicedeck_version,
                mode,
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

    async def _resolve_launch(self) -> tuple[str, AgentPayload | None, str]:
        """Pick the remote command (and optional bundle payload) for the device's agent_mode."""
        mode = self._device.agent_mode
        if mode == "auto":
            mode = "installed" if await self._remote_agent_installed() else "bundled"
            logger.debug("agent_mode=auto resolved to '%s' on %s", mode, self._device.hostname)

        if mode == "installed":
            return self._remote_command, None, mode

        payload = get_agent_payload()
        return stage1_command(len(payload.data)), payload, mode

    async def _remote_agent_installed(self) -> bool:
        """Return True if the installed remote agent executable is on the remote PATH."""
        assert self._conn is not None
        executable = shlex.split(self._remote_command)[0]
        try:
            result = await asyncio.wait_for(
                self._conn.run(f"command -v {shlex.quote(executable)}", check=False),
                timeout=10.0,
            )
        except (asyncssh.Error, OSError, TimeoutError) as exc:
            logger.debug("Probe for %s on %s failed: %s", executable, self._device.hostname, exc)
            return False
        return result.exit_status == 0

    def _start_stderr_drain(self) -> None:
        """Continuously read remote stderr so the SSH window never fills and blocks the agent."""
        assert self._process is not None
        self._stderr_tail.clear()
        self._stderr_task = asyncio.create_task(
            self._drain_stderr(self._process.stderr),
            name=f"servicedeck-stderr-{self._device.id}",
        )

    async def _drain_stderr(self, stream: Any) -> None:
        try:
            while True:
                line = await stream.readline()
                if not line:
                    return
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                self._stderr_tail.append(text)
                level = (
                    logging.WARNING
                    if any(tag in text for tag in ("[ERROR]", "[CRITICAL]", "Traceback"))
                    else logging.DEBUG
                )
                agent_logger.log(level, "[%s] %s", self._device.id, text)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.debug("Stopped reading remote stderr for %s: %s", self._device.id, exc)

    async def _bootstrap_failure(self, reason: str) -> RemoteAgentBootstrapError:
        """Collect exit status and stderr, tear down, and build a descriptive error."""
        exit_status: int | None = None
        if self._process is not None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except Exception:
                pass
            status = getattr(self._process, "exit_status", None)
            exit_status = status if isinstance(status, int) else None
        if self._stderr_task is not None:
            try:
                await asyncio.wait_for(asyncio.shield(self._stderr_task), timeout=1.0)
            except Exception:
                pass

        tail = list(self._stderr_tail)
        await self.disconnect()

        host = self._device.hostname
        too_old = next((line for line in tail if PYTHON_TOO_OLD_MARKER in line), None)
        if too_old is not None:
            msg = (
                f"Cannot start ServiceDeck agent on {host}: {too_old.removeprefix('servicedeck: ')}"
            )
        elif exit_status == 127 and self._launch_mode == "bundled":
            msg = (
                f"Cannot start ServiceDeck agent on {host}: python3 was not found. "
                "Install Python 3.10 or newer on the remote host."
            )
        elif exit_status == 127:
            msg = (
                f"Cannot start ServiceDeck agent on {host}: '{self._remote_command}' was not "
                "found. Install servicedeck there, or use agent mode 'bundled'."
            )
        else:
            last = f" Last output: {tail[-1]}" if tail else ""
            status_txt = f" (exit status {exit_status})" if exit_status is not None else ""
            msg = f"Remote agent on {host} failed to start{status_txt}: {reason}.{last}"

        logger.error(msg)
        return RemoteAgentBootstrapError(
            msg,
            details={
                "hostname": host,
                "mode": self._launch_mode,
                "exit_status": exit_status,
                "stderr_tail": tail,
            },
        )

    async def send_request(
        self,
        request: RequestMessage,
        timeout: float = 30.0,
    ) -> ResponseMessage:
        """Send a RequestMessage to the remote agent and await a correlating ResponseMessage.

        Serializes all traffic across the single SSH stdio channel via an asyncio mutex
        to prevent frame interleaving and concurrent StreamReader reads.
        """
        async with self._lock:
            if not self.is_connected or self._process is None:
                raise RemoteConnectionError(
                    f"Cannot send request {request.id}: connection to {self._device.hostname} is not open",
                    details={"request_id": request.id, "device_id": self._device.id},
                )

            try:
                await write_message(self._process.stdin, request)  # type: ignore[arg-type]
            except Exception as exc:
                logger.error("Failed to write request %d to remote agent: %s", request.id, exc)
                await self.disconnect()
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
                await self.disconnect()
                raise RemoteTimeoutError(
                    request_id=request.id,
                    method=request.method,
                    timeout_seconds=timeout,
                ) from exc
            except Exception as exc:
                await self.disconnect()
                raise RemoteConnectionError(
                    f"Failed to read response to request {request.id} from {self._device.hostname}: {exc}",
                    details={"request_id": request.id},
                ) from exc

            if response is None:
                await self.disconnect()
                raise RemoteConnectionError(
                    f"Remote agent on {self._device.hostname} disconnected unexpectedly while awaiting response to request {request.id}",
                    details={"request_id": request.id},
                )

            if not isinstance(response, ResponseMessage):
                await self.disconnect()
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

        if self._stderr_task is not None and not self._stderr_task.done():
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except (asyncio.CancelledError, Exception):
                pass
        self._stderr_task = None

        self._process = None
        self._conn = None
        self._hello = None


__all__ = ["SSHTransport"]
