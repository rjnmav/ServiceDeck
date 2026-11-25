"""Client side of the backend's Server-Sent Events streams."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable, Iterator
from typing import Any

import httpx

from servicedeck.api_client.exceptions import (
    ServiceDeckConnectionError,
    ServiceDeckStreamError,
)

#: The backend sends a keepalive at least every 15 s; three missed ones mean it is gone.
STREAM_READ_TIMEOUT = 45.0


def iter_sse(lines: Iterator[str]) -> Iterator[tuple[str, Any]]:
    """Parse ``text/event-stream`` lines into ``(event, data)`` pairs (data JSON-decoded)."""
    event = "message"
    data: list[str] = []
    for line in lines:
        if not line:
            if data:
                raw = "\n".join(data)
                try:
                    payload: Any = json.loads(raw)
                except ValueError:
                    payload = raw
                yield event, payload
            event, data = "message", []
            continue
        if line.startswith(":"):
            continue
        field, _, value = line.partition(":")
        value = value.removeprefix(" ")
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)


class EventStream[T]:
    """A live stream from the backend; iterate it, and call :meth:`close` to stop.

    Iteration yields the items ``parse`` builds from each event (``None`` results are
    skipped) and stops after the backend's ``end`` event or after :meth:`close`. An
    ``error`` event raises :class:`ServiceDeckStreamError`; a broken connection raises
    :class:`ServiceDeckConnectionError`.

    :meth:`close` may be called from another thread to stop a blocked iteration; the
    blocked read then returns at the latest with the next keepalive.
    """

    def __init__(
        self,
        client: httpx.Client,
        path: str,
        params: dict[str, Any] | None,
        parse: Callable[[str, Any], T | None],
        *,
        base_url: str = "",
        connect_timeout: float = 10.0,
        raise_for_status: Callable[[httpx.Response], None],
    ) -> None:
        self._parse = parse
        self._closed = threading.Event()
        timeout = httpx.Timeout(connect_timeout, read=STREAM_READ_TIMEOUT)
        request = client.build_request(
            "GET",
            path,
            params=params,
            headers={"Accept": "text/event-stream"},
            timeout=timeout,
        )
        try:
            self._response = client.send(request, stream=True)
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ServiceDeckConnectionError(
                f"Failed to connect to ServiceDeck backend at {base_url}: {exc}"
            ) from exc
        if not self._response.is_success:
            try:
                self._response.read()
                raise_for_status(self._response)
            finally:
                self._response.close()

    @property
    def closed(self) -> bool:
        return self._closed.is_set()

    def __iter__(self) -> Iterator[T]:
        try:
            for event, data in iter_sse(self._response.iter_lines()):
                if self._closed.is_set():
                    return
                if event == "end":
                    return
                if event == "error":
                    payload = data if isinstance(data, dict) else {}
                    raise ServiceDeckStreamError(
                        str(payload.get("message") or "The stream failed."),
                        error_type=payload.get("error"),
                    )
                item = self._parse(event, data)
                if item is not None:
                    yield item
            if not self._closed.is_set():
                raise ServiceDeckConnectionError("The backend closed the stream unexpectedly.")
        except (httpx.HTTPError, httpx.StreamError, OSError) as exc:
            if self._closed.is_set():
                return
            raise ServiceDeckConnectionError(f"Lost the stream from the backend: {exc}") from exc
        finally:
            self.close()

    def close(self) -> None:
        """Stop the stream. Safe to call repeatedly and from any thread."""
        if self._closed.is_set():
            return
        self._closed.set()
        try:
            self._response.close()
        except Exception:
            pass

    def __enter__(self) -> EventStream[T]:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


__all__ = ["STREAM_READ_TIMEOUT", "EventStream", "iter_sse"]
