"""Streams over the remote protocol: agent ``ProtocolServer`` <-> backend ``AgentChannel``.

The two ends are wired together in memory, so these tests run the real framing, the
agent's stream handling, the backend's multiplexing, and ``RemoteManager`` on top.
"""

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from tests.conftest import FakeSystemdAdapter

from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    ServiceNotFoundError,
    SystemdConnectionError,
)
from servicedeck.backend.models.service import Service, ServiceEvent
from servicedeck.backend.remote.channel import AgentChannel
from servicedeck.remote.models import (
    CancelMessage,
    EventMessage,
    RequestMessage,
)
from servicedeck.remote.protocol import ProtocolDecoder, ProtocolEncoder, read_message
from servicedeck.remote_agent.dispatcher import RequestDispatcher
from servicedeck.remote_agent.server import ProtocolServer


class PipeWriter:
    """Writes into the reader of the other end, like one direction of a pipe."""

    def __init__(self, reader: asyncio.StreamReader) -> None:
        self._reader = reader
        self._closed = False

    def write(self, data: bytes) -> None:
        if not self._closed:
            self._reader.feed_data(data)

    async def drain(self) -> None:
        await asyncio.sleep(0)

    def is_closing(self) -> bool:
        return self._closed

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._reader.feed_eof()

    async def wait_closed(self) -> None:
        return None


class AgentPair:
    """An agent ``ProtocolServer`` and a backend ``AgentChannel`` connected in memory."""

    def __init__(self, manager: Any) -> None:
        self.agent_in = asyncio.StreamReader()
        self.agent_out = asyncio.StreamReader()
        self.backend_writer = PipeWriter(self.agent_in)
        self.server = ProtocolServer(
            RequestDispatcher(manager), self.agent_in, PipeWriter(self.agent_out)
        )
        self.process = MagicMock()
        self.process.stdin = self.backend_writer
        self.process.stdout = self.agent_out
        self.process.is_closing.return_value = False
        self.channel: AgentChannel | None = None
        self._ids = iter(range(1, 10_000))

    async def __aenter__(self) -> "AgentPair":
        self.server_task = asyncio.create_task(self.server.run())
        hello = await read_message(self.agent_out)
        assert hello is not None and hello.type == "hello"
        self.channel = AgentChannel(self.process, "srv.test", "srv")
        return self

    async def __aexit__(self, *exc: object) -> None:
        self.backend_writer.close()
        with contextlib.suppress(Exception):
            await asyncio.wait_for(self.server_task, 2)
        assert self.channel is not None
        await self.channel.close()

    def request(self, method: str, **params: Any) -> RequestMessage:
        return RequestMessage(id=next(self._ids), method=method, params=params)


class ControlledManager:
    """A ServiceManager stand-in whose service watch stays open until released."""

    def __init__(self) -> None:
        self.queue: asyncio.Queue[ServiceEvent | Exception | None] = asyncio.Queue()
        self.closed = asyncio.Event()

    async def watch_services(self, scope: str | None = None) -> AsyncIterator[ServiceEvent]:
        try:
            yield ServiceEvent(kind="ready", scope=scope or "user")
            while True:
                item = await self.queue.get()
                if item is None:
                    return
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            self.closed.set()

    async def is_healthy(self, scope: str | None = None) -> bool:
        return True


def _svc(name: str, active: str = "active") -> Service:
    return Service(
        name=name,
        description="",
        load_state="loaded",
        active_state=active,
        sub_state="running" if active == "active" else "failed",
        unit_file_state="enabled",
        scope="user",
    )


def test_event_and_cancel_messages_round_trip() -> None:
    encoder, decoder = ProtocolEncoder(), ProtocolDecoder()
    decoder.feed(encoder.encode(EventMessage(stream=7, event="log", data={"line": "hi"})))
    decoder.feed(encoder.encode(CancelMessage(stream=7)))
    assert decoder.get_messages() == [
        EventMessage(stream=7, event="log", data={"line": "hi"}),
        CancelMessage(stream=7),
    ]


async def test_service_stream_delivers_scripted_events_then_end() -> None:
    adapter = FakeSystemdAdapter()
    adapter.watch_events = [
        ServiceEvent(kind="changed", scope="user", name="a.service", service=_svc("a.service")),
        ServiceEvent(kind="removed", scope="user", name="b.service"),
    ]
    async with AgentPair(ServiceManager(adapter)) as pair:
        assert pair.channel is not None
        response, stream = await pair.channel.open_stream(
            pair.request("stream.services", scope="user"), timeout=5
        )
        assert response.success
        assert stream is not None
        assert response.result == {"stream": stream.stream_id}

        items = [item async for item in stream]
        assert [event for event, _ in items] == ["service", "removed", "end"]
        assert items[0][1]["name"] == "a.service"
        assert items[1][1] == {"name": "b.service", "scope": "user"}
        assert items[2][1] is None


async def test_requests_are_served_while_a_stream_is_open_and_cancel_stops_it() -> None:
    manager = ControlledManager()
    async with AgentPair(manager) as pair:
        assert pair.channel is not None
        _, stream = await pair.channel.open_stream(pair.request("stream.services"), timeout=5)
        assert stream is not None

        health = await pair.channel.request(pair.request("health.check"), timeout=5)
        assert health.result == {"healthy": True}

        manager.queue.put_nowait(ServiceEvent(kind="resync", scope="user"))
        assert await asyncio.wait_for(anext(stream), 2) == ("resync", {"scope": "user"})

        await stream.aclose()
        await asyncio.wait_for(manager.closed.wait(), 2)
        assert not pair.server._streams


async def test_stream_that_cannot_start_returns_error_response() -> None:
    async with AgentPair(ServiceManager(FakeSystemdAdapter())) as pair:
        assert pair.channel is not None
        response, stream = await pair.channel.open_stream(
            pair.request("stream.logs", name="missing", scope="user"), timeout=5
        )
        assert stream is None
        assert not response.success
        assert response.error is not None
        assert response.error.code == "SERVICE_NOT_FOUND"


async def test_stream_error_arrives_as_end_event_with_error() -> None:
    manager = ControlledManager()
    async with AgentPair(manager) as pair:
        assert pair.channel is not None
        _, stream = await pair.channel.open_stream(pair.request("stream.services"), timeout=5)
        assert stream is not None
        manager.queue.put_nowait(SystemdConnectionError("bus lost"))
        event, data = await asyncio.wait_for(anext(stream), 2)
        assert event == "end"
        assert data["error"]["code"] == "SYSTEMD_CONNECTION_ERROR"


async def test_channel_loss_fails_open_streams() -> None:
    manager = ControlledManager()
    async with AgentPair(manager) as pair:
        assert pair.channel is not None
        _, stream = await pair.channel.open_stream(pair.request("stream.services"), timeout=5)
        assert stream is not None
        pair.agent_out.feed_eof()
        with pytest.raises(RemoteConnectionError, match="disconnected unexpectedly"):
            await asyncio.wait_for(anext(stream), 2)
        assert pair.channel.closed


# --- RemoteManager on top of the agent pair ---


class PairTransport:
    """Duck-typed SSHTransport that routes streams to an in-memory agent."""

    def __init__(self, pair: AgentPair, root_pair: AgentPair | None = None) -> None:
        self.pair = pair
        self.root_pair = root_pair
        self.is_connected = True

    async def open_stream(self, request: RequestMessage, timeout: float = 30.0) -> Any:
        assert self.pair.channel is not None
        return await self.pair.channel.open_stream(request, timeout)

    async def open_privileged_stream(self, request: RequestMessage, timeout: float = 30.0) -> Any:
        assert self.root_pair is not None and self.root_pair.channel is not None
        return await self.root_pair.channel.open_stream(request, timeout)


def _remote_manager(transport: PairTransport, *, elevated: bool = False) -> RemoteManager:
    connections = MagicMock()
    connections.get_transport.return_value = transport
    connections.is_elevated.return_value = elevated
    return RemoteManager(connection_manager=connections, config_manager=MagicMock())


async def test_remote_manager_watch_services_yields_domain_events() -> None:
    adapter = FakeSystemdAdapter()
    adapter.watch_events = [
        ServiceEvent(kind="changed", scope="user", name="a.service", service=_svc("a.service")),
        ServiceEvent(kind="resync", scope="user"),
    ]
    async with AgentPair(ServiceManager(adapter)) as pair:
        manager = _remote_manager(PairTransport(pair))
        events = [event async for event in manager.watch_services("srv")]
        assert [e.kind for e in events] == ["ready", "changed", "resync"]
        assert events[1].service == _svc("a.service")


async def test_remote_manager_watch_raises_error_carried_by_end_event() -> None:
    manager_stub = ControlledManager()
    async with AgentPair(manager_stub) as pair:
        manager = _remote_manager(PairTransport(pair))
        events = manager.watch_services("srv")
        assert (await anext(events)).kind == "ready"
        manager_stub.queue.put_nowait(SystemdConnectionError("bus lost"))
        with pytest.raises(SystemdConnectionError, match="bus lost"):
            await asyncio.wait_for(anext(events), 2)


async def test_remote_manager_follow_logs_and_unknown_service() -> None:
    adapter = FakeSystemdAdapter()
    adapter.followed_logs[("user", "pipewire.service")] = ["a", "b"]
    async with AgentPair(ServiceManager(adapter)) as pair:
        manager = _remote_manager(PairTransport(pair))
        lines = [line async for line in manager.follow_service_logs("srv", "pipewire", lines=2)]
        assert lines == ["", "a", "b"]

        with pytest.raises(ServiceNotFoundError):
            await anext(manager.follow_service_logs("srv", "missing"))


async def test_remote_manager_reads_system_logs_as_root_when_elevated() -> None:
    user_adapter, root_adapter = FakeSystemdAdapter(), FakeSystemdAdapter()
    root_adapter.followed_logs[("system", "ssh.service")] = ["from root"]
    async with (
        AgentPair(ServiceManager(user_adapter)) as pair,
        AgentPair(ServiceManager(root_adapter)) as root_pair,
    ):
        manager = _remote_manager(PairTransport(pair, root_pair), elevated=True)
        lines = [line async for line in manager.follow_service_logs("srv", "ssh", scope="system")]
        assert lines == ["", "from root"]
        assert not any(call[0] == "follow_service_logs" for call in user_adapter.calls)
