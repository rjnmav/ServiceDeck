"""Administrator session on this computer, for system-scope unit file changes.

The backend runs unprivileged. Service lifecycle calls on the system bus are authorized by
Polkit, but systemd's D-Bus API has no call for writing unit files, so creating a system
unit or a drop-in under ``/etc/systemd/system`` needs root. As for remote hosts (Cockpit's
"superuser" model), a root copy of the agent is started with sudo once, after the user enters
their password, and system-scope file changes are sent to it until the session is dropped or
has been idle for ``idle_timeout`` seconds.

Only file-changing calls are routed here; everything else keeps using the backend's own
D-Bus connections (and Polkit).
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol, TypeVar

from servicedeck.backend.core.security_logger import log_local_elevation
from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    LocalElevationRequiredError,
    RemoteConnectionError,
    RemoteSudoAuthError,
    RemoteSudoUnavailableError,
)
from servicedeck.backend.remote.errors import exception_from_response
from servicedeck.remote.models import HelloMessage, RequestMessage, ResponseMessage

logger = logging.getLogger(__name__)

T = TypeVar("T")

DEFAULT_IDLE_TIMEOUT = 900.0


class RootAgent(Protocol):
    """What the session needs from a root agent (``LocalPrivilegedAgent`` in production)."""

    @property
    def is_alive(self) -> bool: ...

    async def start(self, password: str | None, timeout: float = 30.0) -> HelloMessage: ...

    async def send_request(
        self, request: RequestMessage, timeout: float = 30.0
    ) -> ResponseMessage: ...

    async def close(self) -> None: ...


def _default_agent_factory() -> RootAgent:
    from servicedeck.backend.remote.privileged import LocalPrivilegedAgent

    return LocalPrivilegedAgent()


class LocalAdminSession:
    """Owns the local root agent and routes system-scope file changes to it."""

    def __init__(
        self,
        idle_timeout: float = DEFAULT_IDLE_TIMEOUT,
        agent_factory: Callable[[], RootAgent] = _default_agent_factory,
    ) -> None:
        self._idle_timeout = idle_timeout
        self._agent_factory = agent_factory
        self._agent: RootAgent | None = None
        self._lock = asyncio.Lock()
        self._ids = itertools.count(1)
        self._last_used = 0.0
        self._idle_task: asyncio.Task[None] | None = None

    @property
    def is_elevated(self) -> bool:
        return self._agent is not None and self._agent.is_alive

    @property
    def idle_timeout(self) -> float:
        return self._idle_timeout

    async def elevate(self, password: str | None) -> None:
        """Start the root agent. ``None`` tries passwordless sudo (``sudo -n``)."""
        async with self._lock:
            if self.is_elevated:
                return
            await self._drop_locked(log=False)
            agent = self._agent_factory()
            try:
                await agent.start(password)
            except (RemoteSudoAuthError, RemoteSudoUnavailableError) as exc:
                log_local_elevation("denied", reason=type(exc).__name__)
                raise
            finally:
                del password
            self._agent = agent
            self._touch()
            if self._idle_timeout > 0:
                self._idle_task = asyncio.create_task(
                    self._watch_idle(), name="servicedeck-local-admin-idle"
                )
        log_local_elevation("granted")

    async def drop(self) -> None:
        """Stop the root agent; system unit file changes need the password again."""
        async with self._lock:
            await self._drop_locked(log=True)

    async def close(self) -> None:
        await self.drop()

    async def _drop_locked(self, *, log: bool, reason: str | None = None) -> None:
        agent, self._agent = self._agent, None
        task, self._idle_task = self._idle_task, None
        if task is not None and task is not asyncio.current_task():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if agent is not None:
            with contextlib.suppress(Exception):
                await agent.close()
            if log:
                log_local_elevation("dropped", reason=reason)

    def _touch(self) -> None:
        self._last_used = time.monotonic()

    async def _watch_idle(self) -> None:
        while True:
            remaining = self._last_used + self._idle_timeout - time.monotonic()
            if remaining > 0:
                await asyncio.sleep(remaining)
                continue
            async with self._lock:
                if self._last_used + self._idle_timeout <= time.monotonic():
                    logger.info("Dropping local administrator access after idle timeout")
                    await self._drop_locked(log=True, reason="idle")
                    return

    async def request(self, method: str, params: dict[str, Any], timeout: float = 60.0) -> Any:
        """Run one agent method as root and return its result (or raise its error)."""
        agent = self._agent
        if agent is None or not agent.is_alive:
            raise LocalElevationRequiredError(
                "Administrator access on this computer is required.",
                details=self._details(method, params),
            )
        self._touch()
        request = RequestMessage(id=next(self._ids), method=method, params=params)
        try:
            response = await agent.send_request(request, timeout=timeout)
        except RemoteConnectionError as exc:
            async with self._lock:
                await self._drop_locked(log=True, reason="agent-ended")
            raise LocalElevationRequiredError(
                "The administrator session ended; administrator access is needed again.",
                details=self._details(method, params),
            ) from exc
        finally:
            self._touch()
        if not response.success:
            raise exception_from_response(method, params, response)
        return response.result

    async def run_system_write(
        self,
        scope: str,
        method: str,
        params: dict[str, Any],
        local_call: Callable[[], Awaitable[T]],
        from_agent: Callable[[Any], T],
    ) -> T:
        """Run a unit-file change: as root while elevated, else in-process.

        A system-scope change the backend is not allowed to make becomes
        ``LocalElevationRequiredError`` so the client can ask for the password and retry.
        ``from_agent`` converts the root agent's JSON result to what ``local_call`` returns.
        """
        if scope == "system" and self.is_elevated:
            return from_agent(await self.request(method, {**params, "scope": scope}))
        try:
            return await local_call()
        except AuthorizationDeniedError as exc:
            if scope != "system":
                raise
            raise LocalElevationRequiredError(
                f"{exc.message} Enter the administrator password to continue.",
                details={**exc.details, **self._details(method, params)},
            ) from exc

    @staticmethod
    def _details(method: str, params: dict[str, Any]) -> dict[str, Any]:
        return {
            "device_id": None,
            "action": method,
            "service_name": params.get("name"),
            "scope": "system",
        }


__all__ = ["DEFAULT_IDLE_TIMEOUT", "LocalAdminSession", "RootAgent"]
