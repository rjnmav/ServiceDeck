"""Unit tests for the Server-Sent Events endpoints (live updates and followed logs)."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from httpx import AsyncClient
from tests.conftest import FakeSystemdAdapter

from servicedeck.backend.api.sse import _sse_body, format_sse
from servicedeck.backend.exceptions import SystemdConnectionError
from servicedeck.backend.models.service import Service, ServiceEvent


def parse_sse(text: str) -> list[tuple[str, Any]]:
    events: list[tuple[str, Any]] = []
    for block in text.split("\n\n"):
        name, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                name = line[len("event: ") :]
            elif line.startswith("data: "):
                data = json.loads(line[len("data: ") :])
        if name is not None:
            events.append((name, data))
    return events


def _svc(name: str, active: str = "active", sub: str = "running") -> Service:
    return Service(
        name=name,
        description="Demo",
        load_state="loaded",
        active_state=active,
        sub_state=sub,
        unit_file_state="enabled",
        scope="user",
    )


async def test_events_stream_sends_ready_changes_and_end(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.watch_events = [
        ServiceEvent(kind="changed", scope="user", name="a.service", service=_svc("a.service")),
        ServiceEvent(kind="removed", scope="user", name="b.service"),
        ServiceEvent(kind="resync", scope="user"),
    ]

    response = await client.get("/api/events")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(response.text)
    assert [name for name, _ in events] == ["ready", "service", "removed", "resync", "end"]
    assert events[0][1] == {"scope": "user"}
    assert events[1][1]["name"] == "a.service"
    assert events[1][1]["active_state"] == "active"
    assert events[2][1] == {"name": "b.service", "scope": "user"}
    assert fake_adapter.closed_streams == ["watch"]


async def test_events_stream_uses_requested_scope(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    response = await client.get("/api/events?scope=system")
    assert response.status_code == 200
    assert ("watch_services", "*", "system") in fake_adapter.calls


async def test_events_stream_reports_error_event(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.stream_error = SystemdConnectionError("bus went away")

    response = await client.get("/api/events")

    events = parse_sse(response.text)
    assert events[-1] == ("error", {"error": "SystemdConnectionError", "message": "bus went away"})


async def test_follow_logs_streams_lines(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.followed_logs[("user", "pipewire.service")] = ["one", "two"]

    response = await client.get("/api/services/pipewire/logs/follow?lines=5")

    assert response.status_code == 200
    events = parse_sse(response.text)
    assert events == [
        ("ready", {"service": "pipewire.service", "scope": "user"}),
        ("log", {"line": "one"}),
        ("log", {"line": "two"}),
        ("end", None),
    ]
    assert ("follow_service_logs", "pipewire.service", "user") in fake_adapter.calls


async def test_follow_logs_unknown_service_is_404_before_streaming(client: AsyncClient) -> None:
    response = await client.get("/api/services/missing/logs/follow")
    assert response.status_code == 404
    assert response.json()["error"] == "ServiceNotFoundError"


async def test_follow_logs_invalid_name_is_400(client: AsyncClient) -> None:
    response = await client.get("/api/services/bad%20name/logs/follow")
    assert response.status_code == 400


async def test_sse_body_sends_keepalive_while_idle() -> None:
    release = asyncio.Event()

    async def slow() -> AsyncIterator[str]:
        await release.wait()
        yield "late"

    body = _sse_body(slow(), lambda line: ("log", {"line": line}), [("ready", None)], 0.01)
    assert await anext(body) == format_sse("ready", None)
    assert await anext(body) == ": keepalive\n\n"
    release.set()
    rest = [chunk async for chunk in body]
    assert format_sse("log", {"line": "late"}) in rest
    assert rest[-1] == format_sse("end", None)


async def test_sse_body_closes_source_when_client_goes_away() -> None:
    closed = asyncio.Event()

    async def endless() -> AsyncIterator[str]:
        try:
            while True:
                yield "x"
                await asyncio.sleep(0.001)
        finally:
            closed.set()

    body = _sse_body(endless(), lambda line: ("log", {"line": line}), [], 1.0)
    await anext(body)
    await body.aclose()
    await asyncio.wait_for(closed.wait(), timeout=1.0)
