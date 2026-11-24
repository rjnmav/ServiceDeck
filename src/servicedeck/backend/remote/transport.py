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
from servicedeck.backend.remote.channel import drain_stderr, exchange_request
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.known_hosts import KnownHostsStore
from servicedeck.backend.remote.privileged import PrivilegedAgent
from servicedeck.remote.exceptions import RemoteProtocolError, RemoteTimeoutError
from servicedeck.remote.models import (
    GoodbyeMessage,
    HelloMessage,
    RequestMessage,
    ResponseMessage,
)
from servicedeck.remote.protocol import ProtocolEncoder, read_message, write_message

logger = logging.getLogger(__name__)

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
        known_hosts: KnownHostsStore | None = None,
    ) -> None:
        self._device = device
        self._remote_command = remote_command
        self._known_hosts = known_hosts or KnownHostsStore()
        self._conn: asyncssh.SSHClientConnection | None = None
        self._process: asyncssh.SSHClientProcess | None = None
        self._hello: HelloMessage | None = None
        self._encoder = ProtocolEncoder()
        self._lock = asyncio.Lock()
        self._launch_mode: str | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=_STDERR_TAIL_LINES)
        self._privileged: PrivilegedAgent | None = None

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
            "known_hosts": self._known_hosts.paths(),
        }
        if self._device.ssh_key_path:
            connect_kwargs["client_keys"] = [self._device.ssh_key_path]

        try:
            self._conn = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=timeout,
            )
        except asyncssh.HostKeyNotVerifiable as exc:
            raise await self._host_key_error(exc) from exc
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

    async def _host_key_error(self, exc: Exception) -> RemoteConnectionError:
        """Tell an untrusted (first-contact) host key apart from a changed one."""
        try:
            info = await self._known_hosts.check(self._device.hostname, self._device.port)
        except RemoteConnectionError as check_exc:
            logger.debug("Could not classify host key of %s: %s", self._device.hostname, check_exc)
            msg = f"SSH host key verification failed for {self._device.hostname}: {exc}"
            logger.error(msg)
            return RemoteHostKeyChangedError(msg, details={"hostname": self._device.hostname})
        error = self._known_hosts.unverified_error(info)
        if info.status == "changed":
            logger.error(error.message)
        else:
            logger.info("Host key of %s is not trusted yet (%s)", info.hostname, info.fingerprint)
        return error

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
        await drain_stderr(stream, self._device.id, self._stderr_tail)

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
                return await exchange_request(
                    self._process, request, timeout, self._device.hostname
                )
            except Exception:
                await self.disconnect()
                raise

    # --- Administrator (root) agent ---

    @property
    def is_elevated(self) -> bool:
        """True while a root agent is running for this connection."""
        return self.is_connected and self._privileged is not None and self._privileged.is_alive

    async def elevate(self, password: str | None, timeout: float = 30.0) -> HelloMessage:
        """Start a root agent through sudo on this connection (no-op if already running).

        ``password`` is used once to answer sudo and is not kept. ``None`` tries
        passwordless sudo (``sudo -n``).
        """
        if self.is_elevated:
            assert self._privileged is not None and self._privileged.hello is not None
            return self._privileged.hello
        if not self.is_connected or self._conn is None:
            raise RemoteConnectionError(
                f"Cannot get administrator access: {self._device.hostname} is not connected",
                details={"device_id": self._device.id},
            )
        await self.drop_privileges()
        agent = PrivilegedAgent(
            self._conn,
            hostname=self._device.hostname,
            label=self._device.id,
            launch_mode=self._launch_mode or "bundled",
            remote_command=self._remote_command,
        )
        hello = await agent.start(password, timeout=timeout)
        self._privileged = agent
        return hello

    async def send_privileged_request(
        self, request: RequestMessage, timeout: float = 30.0
    ) -> ResponseMessage:
        """Send ``request`` to the root agent; fails if administrator access has ended."""
        if not self.is_elevated or self._privileged is None:
            raise RemoteConnectionError(
                f"No administrator session is open on {self._device.hostname}",
                details={"device_id": self._device.id},
            )
        return await self._privileged.send_request(request, timeout=timeout)

    async def drop_privileges(self) -> None:
        """Stop the root agent, if any. The normal agent keeps running."""
        agent, self._privileged = self._privileged, None
        if agent is not None:
            await agent.close()
            logger.info("Administrator access on %s dropped", self._device.hostname)

    async def disconnect(self) -> None:
        """Gracefully terminate agent session and close SSH connection."""
        logger.info("Disconnecting from %s (%s)", self._device.display_name, self._device.hostname)
        await self.drop_privileges()

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
