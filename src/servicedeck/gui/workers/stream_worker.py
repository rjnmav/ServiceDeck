"""Background reader for the backend's live streams (service events, followed logs).

A stream can stay open for hours, so it runs on its own daemon thread instead of the
shared QThreadPool, where it would permanently take a slot from short API calls.
Items reach the GUI thread through queued Qt signals. Every signal carries the worker's
``token`` so a receiver can ignore a stream it has already replaced.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable, Iterable
from typing import Any, Protocol

from PySide6.QtCore import QObject, Signal

from servicedeck.api_client.exceptions import (
    ServiceDeckAPIError,
    ServiceDeckConnectionError,
)

_tokens = itertools.count(1)


class ClosableStream(Protocol):
    def __iter__(self) -> Any: ...

    def close(self) -> None: ...


class StreamSignals(QObject):
    """Signals of a :class:`StreamWorker`; every one starts with the worker's token."""

    item = Signal(int, object)
    #: The stream could not be opened or broke: (token, message, exception).
    failed = Signal(int, str, object)
    #: Always emitted last, after the stream ended for any reason.
    finished = Signal(int)


class StreamWorker:
    """Opens a stream with ``open_stream()`` and emits each item until stopped."""

    def __init__(self, open_stream: Callable[[], Iterable[Any]], *, name: str = "stream") -> None:
        self.token = next(_tokens)
        self.signals = StreamSignals()
        self._open_stream = open_stream
        self._stream: Any = None
        self._stopped = threading.Event()
        self._lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._run, name=f"servicedeck-{name}-{self.token}", daemon=True
        )

    @property
    def stopped(self) -> bool:
        return self._stopped.is_set()

    def start(self) -> StreamWorker:
        self._thread.start()
        return self

    def stop(self) -> None:
        """Ask the stream to stop. Returns at once; no further items are emitted."""
        self._stopped.set()
        with self._lock:
            stream = self._stream
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass

    def _run(self) -> None:
        try:
            stream = self._open_stream()
            with self._lock:
                self._stream = stream
            if self._stopped.is_set():
                stream.close()  # type: ignore[attr-defined]
                return
            for item in stream:
                if self._stopped.is_set():
                    break
                self.signals.item.emit(self.token, item)
        except ServiceDeckConnectionError as exc:
            if not self._stopped.is_set():
                self.signals.failed.emit(self.token, f"Connection error: {exc.message}", exc)
        except ServiceDeckAPIError as exc:
            if not self._stopped.is_set():
                self.signals.failed.emit(self.token, exc.message, exc)
        except Exception as exc:
            if not self._stopped.is_set():
                self.signals.failed.emit(self.token, f"Unexpected error: {exc}", exc)
        finally:
            self.signals.finished.emit(self.token)


__all__ = ["StreamSignals", "StreamWorker"]
