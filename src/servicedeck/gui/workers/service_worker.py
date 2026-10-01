"""Background worker system using QRunnable and Qt signals to avoid blocking GUI."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from servicedeck.api_client.exceptions import (
    ServiceDeckAPIError,
    ServiceDeckConnectionError,
)


class WorkerSignals(QObject):
    """Signals for background task execution."""

    started = Signal()
    finished = Signal(object)
    error = Signal(str, object)


class ServiceWorker(QRunnable):
    """QRunnable task executing a callable in a background thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        """Execute the worker task and emit appropriate signals."""
        self.signals.started.emit()
        try:
            result = self.fn(*self.args, **self.kwargs)
            self.signals.finished.emit(result)
        except ServiceDeckConnectionError as exc:
            self.signals.error.emit(
                f"Connection error: {exc.message}",
                exc,
            )
        except ServiceDeckAPIError as exc:
            self.signals.error.emit(
                f"API error: {exc.message}",
                exc,
            )
        except Exception as exc:
            self.signals.error.emit(
                f"Unexpected error: {exc}",
                exc,
            )


_active_workers: set["ServiceWorker"] = set()


def run_async_task(
    fn: Callable[..., Any],
    *args: Any,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[str, Any], None] | None = None,
    on_start: Callable[[], None] | None = None,
    **kwargs: Any,
) -> ServiceWorker:
    """Schedule a callable on the global QThreadPool with optional callbacks."""
    worker = ServiceWorker(fn, *args, **kwargs)
    _active_workers.add(worker)

    def _cleanup(*_: Any) -> None:
        _active_workers.discard(worker)

    worker.signals.finished.connect(_cleanup)
    worker.signals.error.connect(lambda *_: _cleanup())

    if on_start:
        worker.signals.started.connect(on_start)
    if on_success:
        worker.signals.finished.connect(on_success)
    if on_error:
        worker.signals.error.connect(on_error)

    QThreadPool.globalInstance().start(worker)
    return worker
