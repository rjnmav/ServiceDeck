"""Administrator access on remote devices: the sudo handshake and system-scope routing."""

import asyncio
import logging
from collections.abc import Callable
from unittest.mock import AsyncMock, MagicMock

import pytest

from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    RemoteConnectionError,
    RemoteElevationRequiredError,
    RemoteSudoAuthError,
    RemoteSudoUnavailableError,
)
from servicedeck.backend.remote.bundle import get_agent_payload
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.privileged import (
    SUDO_PROMPT,
    SUDO_READY,
    PrivilegedAgent,
    sudo_command,
)
from servicedeck.remote.models import HelloMessage, error_response, success_response
from servicedeck.remote.protocol import ProtocolEncoder

PASSWORD = "s3cret-sudo-pass"


class _Stdin:
    """Records writes and lets the fake remote side react to them."""

    def __init__(self, on_write: Callable[[bytes], None]) -> None:
        self.written = bytearray()
        self._on_write = on_write
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)
        self._on_write(bytes(data))

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeSudo:
    """A remote ``sudo`` channel scripted by how it should answer the password."""

    def __init__(
        self,
        *,
        prompt: bool = True,
        accept: str | None = PASSWORD,
        uid: int = 0,
        exit_text: bytes | None = None,
    ) -> None:
        self.stderr = asyncio.StreamReader()
        self.stdout = asyncio.StreamReader()
        self.stdin = _Stdin(self._on_write)
        self.exit_status: int | None = None
        self._uid = uid
        self._accept = accept
        self._state = "auth"
        self._closing = False
        self.payload_len = len(get_agent_payload().data)
        self._received = 0

        if exit_text is not None:
            self._exit(exit_text, 1)
        elif prompt:
            self.stderr.feed_data(SUDO_PROMPT)
        else:
            self._ready()

    def _exit(self, text: bytes, status: int) -> None:
        self.stderr.feed_data(text)
        self.stderr.feed_eof()
        self.stdout.feed_eof()
        self.exit_status = status
        self._closing = True

    def _ready(self) -> None:
        self.stderr.feed_data(SUDO_READY + b"\n")
        self._state = "payload"

    def _on_write(self, data: bytes) -> None:
        if self._state == "auth":
            if data == f"{self._accept}\n".encode():
                self._ready()
            else:
                self.stderr.feed_data(b"Sorry, try again.\n" + SUDO_PROMPT)
        elif self._state == "payload":
            self._received += len(data)
            if self._received >= self.payload_len:
                hello = HelloMessage(host="srv", user="root", uid=self._uid)
                self.stdout.feed_data(ProtocolEncoder().encode(hello))
                self._state = "running"

    def is_closing(self) -> bool:
        return self._closing

    async def wait(self) -> None:
        return None

    def close(self) -> None:
        self._closing = True


def _agent(process: FakeSudo) -> tuple[PrivilegedAgent, MagicMock]:
    conn = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    agent = PrivilegedAgent(conn, hostname="srv.test", label="srv", launch_mode="bundled")
    return agent, conn


# --- Command construction ---


def test_sudo_command_shapes() -> None:
    interactive = sudo_command("exec python3 -c x 10", with_password=True)
    assert interactive.startswith("exec sudo -k -S -p servicedeck-sudo-password: -- sh -c ")
    assert "echo servicedeck-sudo-ready >&2; exec python3 -c x 10" in interactive

    passwordless = sudo_command("exec python3 -c x 10", with_password=False)
    assert passwordless.startswith("exec sudo -n -- sh -c ")


# --- Handshake ---


async def test_password_answers_prompt_once_then_root_agent_starts() -> None:
    process = FakeSudo()
    agent, conn = _agent(process)

    hello = await agent.start(PASSWORD, timeout=5)

    assert hello.uid == 0
    assert agent.is_alive
    command = conn.create_process.call_args.args[0]
    assert PASSWORD not in command  # the password only ever travels on stdin
    written = bytes(process.stdin.written)
    assert written.startswith(f"{PASSWORD}\n".encode())
    assert written.count(PASSWORD.encode()) == 1
    assert written[len(PASSWORD) + 1 :] == get_agent_payload().data
    await agent.close()


async def test_passwordless_sudo_needs_no_password() -> None:
    process = FakeSudo(prompt=False)
    agent, conn = _agent(process)

    assert (await agent.start(None, timeout=5)).uid == 0
    assert " -n " in conn.create_process.call_args.args[0]
    assert bytes(process.stdin.written) == get_agent_payload().data
    await agent.close()


async def test_wrong_password_is_not_retried_and_never_leaks(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    process = FakeSudo(accept="something-else")
    agent, _ = _agent(process)

    with pytest.raises(RemoteSudoAuthError) as info:
        await agent.start(PASSWORD, timeout=5)

    assert bytes(process.stdin.written).count(PASSWORD.encode()) == 1
    assert info.value.details["password_required"] is False
    assert PASSWORD not in str(info.value)
    assert PASSWORD not in repr(info.value.details)
    assert PASSWORD not in caplog.text
    assert not agent.is_alive


async def test_password_needed_but_not_given() -> None:
    process = FakeSudo(exit_text=b"sudo: a password is required\n")
    agent, _ = _agent(process)

    with pytest.raises(RemoteSudoAuthError) as info:
        await agent.start(None, timeout=5)
    assert info.value.details["password_required"] is True


@pytest.mark.parametrize(
    ("text", "match"),
    [
        (b"alice is not in the sudoers file.\n", "not allowed to use sudo"),
        (b"sudo: sorry, you must have a tty to run sudo\n", "requiretty"),
        (b"sh: 1: exec: sudo: not found\n", "not installed"),
    ],
)
async def test_sudo_unavailable_reasons(text: bytes, match: str) -> None:
    agent, _ = _agent(FakeSudo(exit_text=text))
    with pytest.raises(RemoteSudoUnavailableError, match=match):
        await agent.start(PASSWORD, timeout=5)


async def test_agent_that_is_not_root_is_rejected() -> None:
    agent, _ = _agent(FakeSudo(uid=1000))
    with pytest.raises(RemoteSudoUnavailableError, match="did not run the agent as root"):
        await agent.start(PASSWORD, timeout=5)
    assert not agent.is_alive


# --- Routing in RemoteManager ---


@pytest.fixture
def device() -> RemoteDevice:
    return RemoteDevice(id="srv", display_name="Srv", hostname="srv.test", username="alice")


def _manager(device: RemoteDevice, *, elevated: bool) -> tuple[RemoteManager, MagicMock]:
    transport = MagicMock()
    transport.send_request = AsyncMock(return_value=success_response(1, result=None))
    transport.send_privileged_request = AsyncMock(return_value=success_response(1, result=None))
    conns = MagicMock()
    conns.get_transport = MagicMock(return_value=transport)
    conns.is_connected = MagicMock(return_value=True)
    conns.is_elevated = MagicMock(return_value=elevated)
    conns.elevate = AsyncMock(return_value=HelloMessage(host="srv", user="root", uid=0))
    conns.drop_privileges = AsyncMock()
    config = MagicMock()
    config.get_device = MagicMock(return_value=device)
    return RemoteManager(connection_manager=conns, config_manager=config), transport


async def test_elevated_system_calls_go_to_root_agent(device: RemoteDevice) -> None:
    manager, transport = _manager(device, elevated=True)

    await manager.restart_service("srv", "nginx.service", scope="system")
    await manager.restart_service("srv", "app.service", scope="user")

    assert transport.send_privileged_request.await_count == 1
    assert transport.send_privileged_request.await_args.args[0].params["name"] == "nginx.service"
    assert transport.send_request.await_args.args[0].params["name"] == "app.service"


@pytest.mark.parametrize("code", ["AUTHENTICATION_REQUIRED", "PERMISSION_DENIED"])
async def test_system_permission_failure_asks_for_elevation(
    device: RemoteDevice, code: str
) -> None:
    manager, transport = _manager(device, elevated=False)
    transport.send_request = AsyncMock(return_value=error_response(1, code, "Not allowed."))

    with pytest.raises(RemoteElevationRequiredError) as info:
        await manager.start_service("srv", "nginx.service", scope="system")
    assert info.value.details["service_name"] == "nginx.service"
    assert info.value.details["device_id"] == "srv"


async def test_user_scope_auth_failure_is_not_an_elevation_request(device: RemoteDevice) -> None:
    manager, transport = _manager(device, elevated=False)
    transport.send_request = AsyncMock(
        return_value=error_response(1, "AUTHENTICATION_REQUIRED", "Polkit prompt needed")
    )
    with pytest.raises(AuthenticationRequiredError) as info:
        await manager.start_service("srv", "app.service", scope="user")
    assert not isinstance(info.value, RemoteElevationRequiredError)


async def test_ended_root_session_is_never_retried_as_normal_user(device: RemoteDevice) -> None:
    manager, transport = _manager(device, elevated=True)
    transport.send_privileged_request = AsyncMock(side_effect=RemoteConnectionError("gone"))

    with pytest.raises(RemoteElevationRequiredError):
        await manager.stop_service("srv", "nginx.service", scope="system")
    transport.send_request.assert_not_awaited()


async def test_elevate_logs_outcome_without_password(
    device: RemoteDevice, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    manager, _ = _manager(device, elevated=False)
    manager.connection_manager.elevate = AsyncMock(  # type: ignore[method-assign]
        side_effect=RemoteSudoAuthError("sudo on srv.test rejected the administrator password.")
    )

    with pytest.raises(RemoteSudoAuthError):
        await manager.elevate("srv", PASSWORD)

    assert "EVENT=remote_elevation" in caplog.text
    assert "outcome=denied" in caplog.text
    assert PASSWORD not in caplog.text
