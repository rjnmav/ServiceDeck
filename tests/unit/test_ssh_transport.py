"""Unit tests for SSHTransport wrapping asyncssh."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import asyncssh
import pytest

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    SSHAuthenticationError,
)
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
