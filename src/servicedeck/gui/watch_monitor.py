"""Watches selected services for failures, on any host and scope, while the GUI runs.

The main window's live stream only follows the host and scope on screen. This monitor keeps
one extra event stream per (host, scope) that has watched services, so a watched service on
a remote server is noticed even while the local list is shown. It emits ``service_failed``
when a watched service *enters* the failed state; services that were already failed when
watching started (or after a reconnect) are not reported again.
"""

from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import Service, ServiceEvent
from servicedeck.gui.workers.service_worker import run_async_task
from servicedeck.gui.workers.stream_worker import StreamWorker

#: Reconnect delays (seconds) for a watch stream that dropped, growing per failure.
WATCH_RETRY_DELAYS = (5, 15, 60, 300)
#: Do not report the same service failing again within this many seconds.
REPEAT_SUPPRESS_SECONDS = 30.0


@dataclass(frozen=True, slots=True, order=True)
class WatchKey:
    """One watched service. ``device_id`` is None for this computer."""

    device_id: str | None
    scope: str
    name: str

    @property
    def group(self) -> tuple[str | None, str]:
        return (self.device_id, self.scope)


class _Group:
    """The stream and known states for one (host, scope)."""

    def __init__(self) -> None:
        self.worker: StreamWorker | None = None
        self.failures = 0
        self.retry = QTimer()
        self.retry.setSingleShot(True)
        self.connected = False


class ServiceWatchMonitor(QObject):
    """Opens watch streams for watched services and reports when one fails."""

    #: (WatchKey, Service): a watched service just entered the failed state.
    service_failed = Signal(object, object)
    #: (device_id, scope, connected, message): a watch stream connected or dropped.
    stream_state_changed = Signal(object, str, bool, str)

    def __init__(
        self,
        client: ServiceDeckClient,
        parent: QObject | None = None,
        retry_delays: tuple[int, ...] = WATCH_RETRY_DELAYS,
    ) -> None:
        super().__init__(parent)
        self._client = client
        self._retry_delays = retry_delays
        self._watched: set[WatchKey] = set()
        self._groups: dict[tuple[str | None, str], _Group] = {}
        self._states: dict[WatchKey, str] = {}
        self._last_reported: dict[WatchKey, float] = {}
        self._retired: dict[int, StreamWorker] = {}
        self._running = True

    # --- Watched set ---

    @property
    def watched(self) -> frozenset[WatchKey]:
        return frozenset(self._watched)

    def is_watched(self, key: WatchKey) -> bool:
        return key in self._watched

    def set_watched(self, keys: Iterable[WatchKey]) -> None:
        """Replace the watched set and open or close streams to match."""
        self._watched = set(keys)
        for key in list(self._states):
            if key not in self._watched:
                del self._states[key]
        self._reconcile()

    def watch(self, key: WatchKey) -> None:
        self.set_watched({*self._watched, key})

    def unwatch(self, key: WatchKey) -> None:
        self.set_watched(self._watched - {key})

    def is_connected(self, device_id: str | None, scope: str) -> bool:
        group = self._groups.get((device_id, scope))
        return group is not None and group.connected

    # --- Streams ---

    def _reconcile(self) -> None:
        if not self._running:
            return
        wanted = {key.group for key in self._watched}
        for group_key in list(self._groups):
            if group_key not in wanted:
                self._close_group(group_key)
        for group_key in wanted:
            if group_key not in self._groups:
                group = _Group()
                group.retry.timeout.connect(lambda gk=group_key: self._open(gk))
                self._groups[group_key] = group
                self._open(group_key)

    def _open(self, group_key: tuple[str | None, str]) -> None:
        group = self._groups.get(group_key)
        if group is None or not self._running:
            return
        device_id, scope = group_key
        client = self._client
        worker = StreamWorker(
            lambda: client.watch_services(scope=scope, device_id=device_id), name="watch"
        )
        worker.signals.item.connect(
            lambda token, event, gk=group_key: self._on_event(gk, token, event)
        )
        worker.signals.failed.connect(
            lambda token, message, _exc, gk=group_key: self._on_dropped(gk, token, message)
        )
        worker.signals.finished.connect(
            lambda token, gk=group_key: self._on_dropped(gk, token, "The watch stream ended.")
        )
        group.worker = worker
        worker.start()

    def _close_group(self, group_key: tuple[str | None, str]) -> None:
        group = self._groups.pop(group_key, None)
        if group is None:
            return
        group.retry.stop()
        if group.worker is not None:
            group.worker.stop()
            self._retired[group.worker.token] = group.worker
            group.worker = None

    def _is_current(self, group_key: tuple[str | None, str], token: int) -> _Group | None:
        group = self._groups.get(group_key)
        if group is None or group.worker is None or group.worker.token != token:
            return None
        return group

    def _on_dropped(self, group_key: tuple[str | None, str], token: int, message: str) -> None:
        self._retired.pop(token, None)
        group = self._is_current(group_key, token)
        if group is None:
            return
        group.worker = None
        group.connected = False
        delay = self._retry_delays[min(group.failures, len(self._retry_delays) - 1)]
        group.failures += 1
        self.stream_state_changed.emit(group_key[0], group_key[1], False, message)
        group.retry.start(int(delay * 1000))

    def _on_event(self, group_key: tuple[str | None, str], token: int, event: ServiceEvent) -> None:
        group = self._is_current(group_key, token)
        if group is None:
            return
        if event.kind in ("ready", "resync"):
            if event.kind == "ready":
                group.failures = 0
                group.connected = True
                self.stream_state_changed.emit(group_key[0], group_key[1], True, "")
            self._prime_states(group_key)
        elif event.kind == "changed" and event.service is not None:
            self._observe(WatchKey(group_key[0], group_key[1], event.service.name), event.service)

    def _prime_states(self, group_key: tuple[str | None, str]) -> None:
        """Learn the current states, so an already-failed service is not reported."""
        device_id, scope = group_key

        def on_success(services: list[Service]) -> None:
            by_name = {service.name: service for service in services}
            for key in self._watched:
                if key.group == group_key and key.name in by_name:
                    # Only fill in what no live event has reported meanwhile.
                    self._states.setdefault(key, by_name[key.name].active_state)

        run_async_task(
            self._client.list_services,
            scope=scope,
            device_id=device_id,
            on_success=on_success,
            on_error=lambda _msg, _exc: None,
        )

    def _observe(self, key: WatchKey, service: Service, now: float | None = None) -> None:
        if key not in self._watched:
            return
        previous = self._states.get(key)
        self._states[key] = service.active_state
        if service.active_state != "failed" or previous == "failed":
            return
        current = time.monotonic() if now is None else now
        last = self._last_reported.get(key)
        if last is not None and current - last < REPEAT_SUPPRESS_SECONDS:
            return
        self._last_reported[key] = current
        self.service_failed.emit(key, service)

    def stop(self) -> None:
        """Close every watch stream (on exit)."""
        self._running = False
        for group_key in list(self._groups):
            self._close_group(group_key)


__all__ = ["REPEAT_SUPPRESS_SECONDS", "ServiceWatchMonitor", "WatchKey"]
