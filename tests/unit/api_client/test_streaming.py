"""Unit tests for the client side of the Server-Sent Events streams."""

import httpx
import pytest

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.exceptions import (
    ServiceDeckConnectionError,
    ServiceDeckStreamError,
    ServiceNotFoundError,
)
from servicedeck.api_client.streaming import iter_sse
from servicedeck.api_client.transport import SyncTransport


def sse(*events: tuple[str, str]) -> bytes:
    return "".join(f"event: {name}\ndata: {data}\n\n" for name, data in events).encode()


def make_client(handler: object) -> tuple[ServiceDeckClient, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)  # type: ignore[operator]

    transport = SyncTransport(base_url="http://test")
    transport._client = httpx.Client(transport=httpx.MockTransport(wrapped), base_url="http://test")
    return ServiceDeckClient(transport=transport), seen


def test_iter_sse_parses_events_comments_and_multiline_data() -> None:
    lines = [": keepalive", "", "event: log", 'data: {"line": "a"}', "", "data: x", "data: y", ""]
    assert list(iter_sse(iter(lines))) == [("log", {"line": "a"}), ("message", "x\ny")]


def test_watch_services_yields_typed_events_and_stops_at_end() -> None:
    body = sse(
        ("ready", '{"scope":"system"}'),
        (
            "service",
            '{"name":"nginx.service","description":"Web","load_state":"loaded",'
            '"active_state":"failed","sub_state":"failed","unit_file_state":"enabled",'
            '"scope":"system"}',
        ),
        ("removed", '{"name":"old.service","scope":"system"}'),
        ("resync", '{"scope":"system"}'),
        ("end", "null"),
        ("service", '{"name":"never.service"}'),
    )
    client, seen = make_client(lambda _req: httpx.Response(200, content=body))

    events = list(client.watch_services(scope="system", device_id="srv1"))

    assert seen[0].url.path == "/api/remote/srv1/events"
    assert seen[0].url.params["scope"] == "system"
    assert [e.kind for e in events] == ["ready", "changed", "removed", "resync"]
    assert events[1].service is not None
    assert events[1].service.is_failed
    assert events[2].name == "old.service"


def test_follow_logs_yields_lines() -> None:
    body = sse(
        ("ready", '{"service":"a.service","scope":"user"}'),
        ("log", '{"line":"first"}'),
        ("log", '{"line":"second"}'),
        ("end", "null"),
    )
    client, seen = make_client(lambda _req: httpx.Response(200, content=body))

    assert list(client.follow_logs("a", lines=5)) == ["first", "second"]
    assert seen[0].url.path == "/api/services/a/logs/follow"
    assert seen[0].url.params["lines"] == "5"


def test_error_event_raises_stream_error() -> None:
    body = sse(("ready", "{}"), ("error", '{"error":"SystemdConnectionError","message":"gone"}'))
    client, _ = make_client(lambda _req: httpx.Response(200, content=body))

    with pytest.raises(ServiceDeckStreamError, match="gone") as exc_info:
        list(client.watch_services())
    assert exc_info.value.error_type == "SystemdConnectionError"


def test_http_error_raises_before_streaming() -> None:
    client, _ = make_client(
        lambda _req: httpx.Response(
            404, json={"error": "ServiceNotFoundError", "message": "nope", "details": {}}
        )
    )
    with pytest.raises(ServiceNotFoundError, match="nope"):
        client.follow_logs("missing")


def test_stream_cut_without_end_is_a_connection_error() -> None:
    client, _ = make_client(lambda _req: httpx.Response(200, content=sse(("ready", "{}"))))
    with pytest.raises(ServiceDeckConnectionError, match="closed the stream"):
        list(client.watch_services())


def test_close_stops_iteration_quietly() -> None:
    body = sse(("ready", "{}"), ("resync", "{}"), ("resync", "{}"), ("end", "null"))
    client, _ = make_client(lambda _req: httpx.Response(200, content=body))

    stream = client.watch_services()
    iterator = iter(stream)
    assert next(iterator).kind == "ready"
    stream.close()
    assert list(iterator) == []
    assert stream.closed


def test_unreachable_backend_raises_connection_error() -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    client, _ = make_client(refuse)
    with pytest.raises(ServiceDeckConnectionError):
        client.watch_services()
