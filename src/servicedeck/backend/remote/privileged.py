"""Administrator (root) agent started through ``sudo`` on an existing SSH connection.

This follows Cockpit's "superuser" model: rather than answering a Polkit prompt for every
action (systemd's ``manage-units`` is ``auth_admin`` without caching for SSH sessions), a
second copy of the agent runs as root for the rest of the session. Root talks to the
system bus directly, so system-service operations need no further authorization.

The wire sequence on the channel is::

    exec sudo [-k -S -p <PROMPT> | -n] -- sh -c 'echo <READY> >&2; exec <agent>'

1. If sudo asks for the password it prints ``PROMPT`` (no newline) on stderr; the password
   is written as one line on stdin. sudo reads it byte by byte, so nothing after the
   newline is consumed.
2. Once authorized, the wrapper prints ``READY`` on stderr and execs the agent.
3. For the bundled agent the zlib payload is then streamed on stdin, exactly as for the
   normal agent, and the agent answers with its hello (which must report uid 0).

The password is held only for step 1 and never logged or included in errors.
"""

from __future__ import annotations

import asyncio
import collections
import contextlib
import logging
import shlex
import time
from typing import Any

import asyncssh

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteSudoAuthError,
    RemoteSudoUnavailableError,
)
from servicedeck.backend.remote.bundle import get_agent_payload, stage1_command
from servicedeck.backend.remote.channel import AgentChannel, RemoteStream, drain_stderr
from servicedeck.remote.models import GoodbyeMessage, HelloMessage, RequestMessage, ResponseMessage
from servicedeck.remote.protocol import read_message, write_message

logger = logging.getLogger(__name__)

SUDO_PROMPT = b"servicedeck-sudo-password:"
SUDO_READY = b"servicedeck-sudo-ready"

_UNAVAILABLE_HINTS = (
    ("not in the sudoers", "the remote user is not allowed to use sudo"),
    ("may not run sudo", "the remote user is not allowed to use sudo"),
    ("is not allowed to execute", "sudoers does not allow this user to run the agent"),
    ("a terminal is required", "sudoers requires a terminal (requiretty)"),
    ("must have a tty", "sudoers requires a terminal (requiretty)"),
)


def sudo_command(agent_command: str, *, with_password: bool) -> str:
    """Wrap ``agent_command`` so it runs as root through sudo, announcing readiness."""
    flags = ["-k", "-S", "-p", SUDO_PROMPT.decode()] if with_password else ["-n"]
    inner = f"echo {SUDO_READY.decode()} >&2; {agent_command}"
    return shlex.join(["exec", "sudo", *flags, "--", "sh", "-c", inner])


class PrivilegedAgent:
    """A root-owned agent channel sharing the device's SSH connection."""

    #: The uid the agent must report in its hello; anything else is refused.
    required_uid = 0

    def __init__(
        self,
        conn: asyncssh.SSHClientConnection,
        *,
        hostname: str,
        label: str,
        launch_mode: str,
        remote_command: str = "servicedeck-remote",
    ) -> None:
        self._conn = conn
        self._hostname = hostname
        self._label = f"{label}:root"
        self._launch_mode = launch_mode
        self._remote_command = remote_command
        self._process: asyncssh.SSHClientProcess | None = None
        self._hello: HelloMessage | None = None
        self._channel: AgentChannel | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: collections.deque[str] = collections.deque(maxlen=20)

    @property
    def is_alive(self) -> bool:
        if self._channel is not None and self._channel.closed:
            return False
        return self._process is not None and not self._process.is_closing()

    @property
    def hello(self) -> HelloMessage | None:
        return self._hello

    async def start(self, password: str | None, timeout: float = 30.0) -> HelloMessage:
        """Run sudo, authenticate, and hand-shake with the root agent."""
        payload = get_agent_payload() if self._launch_mode == "bundled" else None
        agent = stage1_command(len(payload.data)) if payload else f"exec {self._remote_command}"
        command = sudo_command(agent, with_password=password is not None)

        try:
            self._process = await self._conn.create_process(
                command,
                stdin=asyncssh.PIPE,
                stdout=asyncssh.PIPE,
                stderr=asyncssh.PIPE,
                encoding=None,
            )
        except (asyncssh.Error, OSError) as exc:
            raise RemoteConnectionError(
                f"Could not open an administrator session on {self._hostname}: {exc}",
                details={"hostname": self._hostname},
            ) from exc

        try:
            await self._authenticate(password, timeout)
            del password
            self._stderr_task = asyncio.create_task(
                drain_stderr(self._process.stderr, self._label, self._stderr_tail),
                name=f"servicedeck-stderr-{self._label}",
            )
            if payload is not None:
                self._process.stdin.write(payload.data)
                await self._process.stdin.drain()
            hello = await asyncio.wait_for(read_message(self._process.stdout), timeout=timeout)
        except TimeoutError as exc:
            await self.close()
            raise RemoteConnectionError(
                f"Timed out starting the administrator agent on {self._hostname}",
                details={"hostname": self._hostname},
            ) from exc
        except BaseException:
            await self.close()
            raise

        if not isinstance(hello, HelloMessage):
            await self.close()
            last = f" Last output: {self._stderr_tail[-1]}" if self._stderr_tail else ""
            raise RemoteConnectionError(
                f"The administrator agent on {self._hostname} did not start.{last}",
                details={"hostname": self._hostname, "stderr_tail": list(self._stderr_tail)},
            )
        if hello.uid != self.required_uid:
            await self.close()
            raise RemoteSudoUnavailableError(
                f"sudo on {self._hostname} did not run the agent as root (uid {hello.uid}).",
                details={"hostname": self._hostname, "uid": hello.uid},
            )

        self._hello = hello
        self._channel = AgentChannel(self._process, self._hostname, self._label)
        logger.info("Administrator agent running on %s (uid 0)", self._hostname)
        return hello

    async def _authenticate(self, password: str | None, timeout: float) -> None:
        """Answer sudo's prompt (at most once) and wait for the READY marker."""
        assert self._process is not None
        stderr = self._process.stderr
        deadline = time.monotonic() + timeout
        buffer = b""
        answered = False

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            chunk = await asyncio.wait_for(stderr.read(4096), timeout=remaining)
            if not chunk:
                raise await self._sudo_failure(buffer, password_supplied=password is not None)
            buffer += chunk

            if SUDO_READY in buffer:
                return
            if SUDO_PROMPT in buffer:
                if password is None or answered:
                    # A second prompt means the password was wrong; never retry it blindly.
                    raise RemoteSudoAuthError(
                        f"sudo on {self._hostname} rejected the administrator password.",
                        details={"hostname": self._hostname, "password_required": password is None},
                    )
                self._process.stdin.write(f"{password}\n".encode())
                await self._process.stdin.drain()
                answered = True
                buffer = buffer.split(SUDO_PROMPT, 1)[1]

    async def _sudo_failure(self, output: bytes, *, password_supplied: bool) -> Exception:
        """Turn sudo exiting before READY into a specific, password-free error."""
        assert self._process is not None
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self._process.wait(), timeout=2.0)
        status = getattr(self._process, "exit_status", None)
        text = output.replace(SUDO_PROMPT, b"").decode("utf-8", errors="replace").strip()
        lower = text.lower()
        details: dict[str, Any] = {"hostname": self._hostname, "exit_status": status}
        host = self._hostname

        if "password is required" in lower:
            details["password_required"] = True
            return RemoteSudoAuthError(f"sudo on {host} needs the administrator password.", details)
        if "incorrect password" in lower or "try again" in lower:
            details["password_required"] = not password_supplied
            return RemoteSudoAuthError(
                f"sudo on {host} rejected the administrator password.", details
            )
        for needle, reason in _UNAVAILABLE_HINTS:
            if needle in lower:
                return RemoteSudoUnavailableError(
                    f"Administrator access is not available on {host}: {reason}.", details
                )
        if status == 127 or "sudo: not found" in lower or "command not found" in lower:
            return RemoteSudoUnavailableError(
                f"Administrator access is not available on {host}: sudo is not installed.",
                details,
            )
        last = text.splitlines()[-1] if text else "no output"
        return RemoteSudoUnavailableError(f"Administrator access failed on {host}: {last}", details)

    def _require_channel(self, request_id: int) -> AgentChannel:
        if not self.is_alive or self._channel is None:
            raise RemoteConnectionError(
                f"The administrator session on {self._hostname} has ended.",
                details={"request_id": request_id},
            )
        return self._channel

    async def send_request(self, request: RequestMessage, timeout: float = 30.0) -> ResponseMessage:
        channel = self._require_channel(request.id)
        try:
            return await channel.request(request, timeout)
        except Exception:
            await self.close()
            raise

    async def open_stream(
        self, request: RequestMessage, timeout: float = 30.0
    ) -> tuple[ResponseMessage, RemoteStream | None]:
        channel = self._require_channel(request.id)
        try:
            return await channel.open_stream(request, timeout)
        except Exception:
            await self.close()
            raise

    async def close(self) -> None:
        """End the root agent. Safe to call repeatedly."""
        process, self._process = self._process, None
        self._hello = None
        if process is not None and not process.is_closing():
            try:
                await write_message(process.stdin, GoodbyeMessage(reason="drop-privileges"))
                process.stdin.close()
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except Exception as exc:
                logger.debug("Administrator agent shutdown finished with: %s", exc)
                with contextlib.suppress(Exception):
                    process.close()
        if self._stderr_task is not None and not self._stderr_task.done():
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stderr_task
        self._stderr_task = None
        channel, self._channel = self._channel, None
        if channel is not None:
            await channel.close()


__all__ = ["SUDO_PROMPT", "SUDO_READY", "PrivilegedAgent", "sudo_command"]
