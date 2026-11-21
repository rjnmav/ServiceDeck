"""Unit tests for SSHTransport wrapping asyncssh."""

import asyncio
import dataclasses
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from servicedeck.backend.exceptions import (
    RemoteAgentBootstrapError,
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    SSHAuthenticationError,
)
from servicedeck.backend.remote.bundle import get_agent_payload
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.transport import SSHTransport
from servicedeck.remote.exceptions import RemoteTimeoutError
from servicedeck.remote.models import (
    HelloMessage,
    RequestMessage,
    success_response,
)
from servicedeck.remote.protocol import ProtocolEncoder


class MockStreamReader:
    """Mock async reader supplying encoded protocol frames."""

    def __init__(self, data: bytes = b"") -> None:
        self._reader = asyncio.StreamReader()
        if data:
            self._reader.feed_data(data)

    def feed(self, data: bytes) -> None:
        self._reader.feed_data(data)

    def feed_eof(self) -> None:
        self._reader.feed_eof()

    async def readline(self) -> bytes:
        return await self._reader.readline()

    async def readexactly(self, n: int) -> bytes:
        return await self._reader.readexactly(n)


class MockStreamWriter:
    """Mock async writer capturing written bytes."""

    def __init__(self) -> None:
        self.written = bytearray()
        self._closing = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        pass

    def is_closing(self) -> bool:
        return self._closing

    def close(self) -> None:
        self._closing = True


@pytest.fixture
def device() -> RemoteDevice:
    return RemoteDevice(
        id="test-srv",
        display_name="Test Server",
        hostname="192.168.1.100",
        port=22,
        username="alice",
    )


async def test_connect_success(device: RemoteDevice) -> None:
    encoder = ProtocolEncoder()
    hello = HelloMessage(host="test-srv", user="alice", uid=1000, servicedeck_version="2.0.0")
    hello_bytes = encoder.encode(hello)

    mock_stdout = MockStreamReader(hello_bytes)
    mock_stdin = MockStreamWriter()

    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout
    mock_process.is_closing.return_value = False

    mock_conn = MagicMock()
    mock_conn.create_process = AsyncMock(return_value=mock_process)

    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.return_value = mock_conn
        transport = SSHTransport(device=device)

        result = await transport.connect(timeout=5.0)

        assert result.host == "test-srv"
        assert result.user == "alice"
        assert transport.is_connected is True
        assert transport.hello == result


async def test_connect_host_key_failure(device: RemoteDevice) -> None:
    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = asyncssh.HostKeyNotVerifiable("Key changed")
        transport = SSHTransport(device=device)

        with pytest.raises(RemoteHostKeyChangedError, match="host key verification failed"):
            await transport.connect(timeout=5.0)

        assert transport.is_connected is False


async def test_connect_auth_failure(device: RemoteDevice) -> None:
    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = asyncssh.PermissionDenied("Auth failed")
        transport = SSHTransport(device=device)

        with pytest.raises(SSHAuthenticationError, match="SSH authentication failed"):
            await transport.connect(timeout=5.0)

        assert transport.is_connected is False


async def test_connect_timeout(device: RemoteDevice) -> None:
    with patch("asyncssh.connect", new_callable=AsyncMock) as mock_connect:
        mock_connect.side_effect = TimeoutError()
        transport = SSHTransport(device=device)

        with pytest.raises(RemoteConnectionError, match="Connection timeout"):
            await transport.connect(timeout=1.0)


async def test_send_request_success(device: RemoteDevice) -> None:
    encoder = ProtocolEncoder()
    transport = SSHTransport(device=device)

    # Prepare connection state
    resp = success_response(42, result={"services": ["nginx"]})
    resp_bytes = encoder.encode(resp)

    mock_stdout = MockStreamReader(resp_bytes)
    mock_stdin = MockStreamWriter()

    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout
    mock_process.is_closing.return_value = False

    transport._conn = MagicMock()
    transport._process = mock_process
    transport._hello = HelloMessage()

    req = RequestMessage(id=42, method="service.list")
    response = await transport.send_request(req, timeout=5.0)

    assert response.id == 42
    assert response.success is True
    assert response.result == {"services": ["nginx"]}
    assert len(mock_stdin.written) > 0


async def test_send_request_not_connected(device: RemoteDevice) -> None:
    transport = SSHTransport(device=device)
    req = RequestMessage(id=1, method="service.list")

    with pytest.raises(RemoteConnectionError, match="is not open"):
        await transport.send_request(req)


async def test_send_request_timeout(device: RemoteDevice) -> None:
    transport = SSHTransport(device=device)
    mock_stdout = MockStreamReader()  # No data fed
    mock_stdin = MockStreamWriter()

    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout
    mock_process.is_closing.return_value = False

    transport._conn = MagicMock()
    transport._process = mock_process

    req = RequestMessage(id=77, method="service.slow")
    with pytest.raises(RemoteTimeoutError, match="timed out"):
        await transport.send_request(req, timeout=0.01)


async def test_send_request_eof(device: RemoteDevice) -> None:
    transport = SSHTransport(device=device)
    mock_stdout = MockStreamReader()
    mock_stdout.feed_eof()
    mock_stdin = MockStreamWriter()

    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout
    mock_process.is_closing.return_value = False

    transport._conn = MagicMock()
    transport._process = mock_process

    req = RequestMessage(id=88, method="service.crash")
    with pytest.raises(RemoteConnectionError, match="disconnected unexpectedly"):
        await transport.send_request(req, timeout=1.0)


async def test_send_request_concurrency_serialized(device: RemoteDevice) -> None:
    """Verify that concurrent send_request calls are strictly serialized across stdio."""
    encoder = ProtocolEncoder()
    transport = SSHTransport(device=device)

    mock_stdin = MockStreamWriter()
    mock_stdout = asyncio.StreamReader()

    mock_process = MagicMock()
    mock_process.stdin = mock_stdin
    mock_process.stdout = mock_stdout
    mock_process.is_closing.return_value = False

    transport._conn = MagicMock()
    transport._process = mock_process

    req1 = RequestMessage(id=1, method="service.resources")
    resp1 = success_response(1, result={"cpu": 10})
    resp1_bytes = encoder.encode(resp1)

    req2 = RequestMessage(id=2, method="service.list")
    resp2 = success_response(2, result=[{"name": "foo"}])
    resp2_bytes = encoder.encode(resp2)

    order: list[int] = []

    async def call_req1() -> Any:
        res = await transport.send_request(req1, timeout=5.0)
        order.append(res.id)
        return res

    async def call_req2() -> Any:
        await asyncio.sleep(0.01)
        res = await transport.send_request(req2, timeout=5.0)
        order.append(res.id)
        return res

    mock_stdout.feed_data(resp1_bytes + resp2_bytes)

    r1, r2 = await asyncio.gather(call_req1(), call_req2())
    assert r1.id == 1
    assert r1.result == {"cpu": 10}
    assert r2.id == 2
    assert r2.result == [{"name": "foo"}]
    assert order == [1, 2]


def _bootstrap_mocks(
    stdout_data: bytes = b"",
    stdout_eof: bool = False,
    stderr_data: bytes = b"",
    exit_status: int | None = None,
) -> tuple[MagicMock, MagicMock, MockStreamWriter]:
    """Build (conn, process, stdin) mocks for exercising agent launch paths."""
    stdout = MockStreamReader(stdout_data)
    if stdout_eof:
        stdout.feed_eof()
    stderr = MockStreamReader(stderr_data)
    stderr.feed_eof()
    stdin = MockStreamWriter()

    process = MagicMock()
    process.stdin = stdin
    process.stdout = stdout
    process.stderr = stderr
    process.is_closing.return_value = False
    process.wait = AsyncMock(return_value=None)
    process.exit_status = exit_status

    conn = MagicMock()
    conn.create_process = AsyncMock(return_value=process)
    conn.wait_closed = AsyncMock(return_value=None)
    conn.run = AsyncMock(return_value=MagicMock(exit_status=1))
    return conn, process, stdin


def _hello_bytes() -> bytes:
    return ProtocolEncoder().encode(
        HelloMessage(host="h", user="alice", uid=1000, servicedeck_version="2.0.0")
    )


def _with_mode(device: RemoteDevice, mode: str) -> RemoteDevice:
    return dataclasses.replace(device, agent_mode=mode)


async def test_connect_bundled_streams_agent_payload(device: RemoteDevice) -> None:
    conn, _, stdin = _bootstrap_mocks(stdout_data=_hello_bytes())
    payload = get_agent_payload()

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=device)
        await transport.connect(timeout=5.0)

    command = conn.create_process.call_args.args[0]
    assert command.startswith("exec python3 -c ")
    assert command.endswith(f" {len(payload.data)}")
    assert bytes(stdin.written) == payload.data
    conn.run.assert_not_called()
    await transport.disconnect()


async def test_connect_installed_mode_runs_remote_command(device: RemoteDevice) -> None:
    conn, _, stdin = _bootstrap_mocks(stdout_data=_hello_bytes())

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=_with_mode(device, "installed"))
        await transport.connect(timeout=5.0)

    assert conn.create_process.call_args.args[0] == "servicedeck-remote"
    assert bytes(stdin.written) == b""
    await transport.disconnect()


@pytest.mark.parametrize(("probe_status", "expect_installed"), [(0, True), (1, False)])
async def test_connect_auto_mode_probes_for_installed_agent(
    device: RemoteDevice, probe_status: int, expect_installed: bool
) -> None:
    conn, _, stdin = _bootstrap_mocks(stdout_data=_hello_bytes())
    conn.run = AsyncMock(return_value=MagicMock(exit_status=probe_status))

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=_with_mode(device, "auto"))
        await transport.connect(timeout=5.0)

    conn.run.assert_awaited_once()
    assert "command -v servicedeck-remote" in conn.run.call_args.args[0]
    command = conn.create_process.call_args.args[0]
    if expect_installed:
        assert command == "servicedeck-remote"
        assert bytes(stdin.written) == b""
    else:
        assert command.startswith("exec python3 -c ")
        assert bytes(stdin.written) == get_agent_payload().data
    await transport.disconnect()


async def test_connect_bundled_reports_missing_python(device: RemoteDevice) -> None:
    conn, _, _ = _bootstrap_mocks(
        stdout_eof=True, stderr_data=b"sh: exec: python3: not found\n", exit_status=127
    )

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=device)
        with pytest.raises(RemoteAgentBootstrapError, match="python3 was not found") as info:
            await transport.connect(timeout=5.0)

    assert info.value.details["exit_status"] == 127
    assert info.value.details["stderr_tail"] == ["sh: exec: python3: not found"]
    assert transport.is_connected is False


async def test_connect_bundled_reports_python_too_old(device: RemoteDevice) -> None:
    conn, _, _ = _bootstrap_mocks(
        stdout_eof=True,
        stderr_data=b"servicedeck: remote python3 >= 3.10 required, found 3.9\n",
        exit_status=1,
    )

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=device)
        with pytest.raises(
            RemoteAgentBootstrapError, match=r"python3 >= 3\.10 required, found 3\.9"
        ):
            await transport.connect(timeout=5.0)


async def test_connect_installed_reports_missing_agent(device: RemoteDevice) -> None:
    conn, _, _ = _bootstrap_mocks(stdout_eof=True, exit_status=127)

    with patch("asyncssh.connect", new_callable=AsyncMock, return_value=conn):
        transport = SSHTransport(device=_with_mode(device, "installed"))
        with pytest.raises(RemoteAgentBootstrapError, match="'servicedeck-remote' was not found"):
            await transport.connect(timeout=5.0)
