"""Watched services: the failure monitor, desktop notifications and the GUI controls."""

import threading
import time
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import (
    Service,
    ServiceEvent,
    ServiceLogs,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.gui.notifications import DesktopNotifier
from servicedeck.gui.preferences import GuiPreferencesStore
from servicedeck.gui.watch_monitor import ServiceWatchMonitor, WatchKey


def _svc(name: str, active: str, scope: str = "user") -> Service:
    return Service(
        name=name,
        description=name.split(".")[0].upper(),
        load_state="loaded",
        active_state=active,
        sub_state={"active": "running", "failed": "failed"}.get(active, "dead"),
        unit_file_state="enabled",
        scope=scope,
    )


def _changed(name: str, active: str, scope: str = "user") -> ServiceEvent:
    service = _svc(name, active, scope)
    return ServiceEvent(kind="changed", scope=scope, name=name, service=service)


class ScriptedStream:
    """An EventStream stand-in: yields the scripted events, then blocks until closed."""

    def __init__(self, events: list[ServiceEvent]) -> None:
        self._events = events
        self._closed = threading.Event()

    def __iter__(self) -> Any:
        yield from self._events
        self._closed.wait(5)

    def close(self) -> None:
        self._closed.set()


def _wait(qapp: Any, condition: Any, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QThreadPool.globalInstance().waitForDone(50)
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not reached")


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=ServiceDeckClient)


# --- Monitor ---


def test_reports_only_transitions_into_failed(qapp: Any, client: MagicMock) -> None:
    client.list_services.return_value = [
        _svc("web.service", "active"),
        _svc("old.service", "failed"),
    ]
    events = [ServiceEvent(kind="ready", scope="user")]
    streams: list[ScriptedStream] = []

    def watch_services(scope: str, device_id: str | None) -> ScriptedStream:
        stream = ScriptedStream(events)
        streams.append(stream)
        return stream

    client.watch_services.side_effect = watch_services
    monitor = ServiceWatchMonitor(client)
    failed: list[tuple[WatchKey, Service]] = []
    monitor.service_failed.connect(lambda key, svc: failed.append((key, svc)))
    web = WatchKey(None, "user", "web.service")
    old = WatchKey(None, "user", "old.service")
    monitor.set_watched({web, old})
    try:
        _wait(qapp, lambda: monitor.is_connected(None, "user") and len(monitor._states) == 2)

        group = (None, "user")
        token = monitor._groups[group].worker.token  # type: ignore[union-attr]
        # Already failed before watching started: not reported again.
        monitor._on_event(group, token, _changed("old.service", "failed"))
        # Unwatched service failing: ignored.
        monitor._on_event(group, token, _changed("other.service", "failed"))
        # A watched service that fails: reported once.
        monitor._on_event(group, token, _changed("web.service", "failed"))
        monitor._on_event(group, token, _changed("web.service", "failed"))
        assert [(k.name, s.sub_state) for k, s in failed] == [("web.service", "failed")]
        assert client.watch_services.call_count == 1  # one stream per (host, scope)
    finally:
        monitor.stop()
    assert all(s._closed.is_set() for s in streams)


def test_repeat_failures_are_rate_limited(qapp: Any, client: MagicMock) -> None:
    monitor = ServiceWatchMonitor(client)
    monitor._running = False  # no streams; drive _observe directly
    key = WatchKey("srv1", "system", "db.service")
    monitor._watched = {key}
    failed: list[WatchKey] = []
    monitor.service_failed.connect(lambda k, _s: failed.append(k))

    monitor._observe(key, _svc("db.service", "failed", "system"), now=100.0)
    monitor._observe(key, _svc("db.service", "activating", "system"), now=101.0)
    monitor._observe(key, _svc("db.service", "failed", "system"), now=110.0)  # too soon
    monitor._observe(key, _svc("db.service", "activating", "system"), now=111.0)
    monitor._observe(key, _svc("db.service", "failed", "system"), now=200.0)
    assert failed == [key, key]


def test_streams_follow_the_watched_groups(qapp: Any, client: MagicMock) -> None:
    client.watch_services.side_effect = lambda scope, device_id: ScriptedStream([])
    monitor = ServiceWatchMonitor(client, retry_delays=(60,))
    try:
        monitor.set_watched(
            {
                WatchKey(None, "user", "a.service"),
                WatchKey(None, "user", "b.service"),
                WatchKey("srv1", "system", "nginx.service"),
            }
        )
        assert set(monitor._groups) == {(None, "user"), ("srv1", "system")}
        _wait(qapp, lambda: client.watch_services.call_count == 2)
        called = {
            (c.kwargs["device_id"], c.kwargs["scope"]) for c in client.watch_services.call_args_list
        }
        assert called == {(None, "user"), ("srv1", "system")}

        monitor.unwatch(WatchKey("srv1", "system", "nginx.service"))
        assert set(monitor._groups) == {(None, "user")}
    finally:
        monitor.stop()


def test_dropped_stream_is_retried(qapp: Any, client: MagicMock) -> None:
    from servicedeck.api_client.exceptions import ServiceDeckConnectionError

    calls: list[int] = []

    def watch_services(scope: str, device_id: str | None) -> ScriptedStream:
        calls.append(1)
        if len(calls) == 1:
            raise ServiceDeckConnectionError("backend down")
        return ScriptedStream([ServiceEvent(kind="ready", scope=scope)])

    client.watch_services.side_effect = watch_services
    client.list_services.return_value = []
    monitor = ServiceWatchMonitor(client, retry_delays=(0.05,))  # type: ignore[arg-type]
    states: list[bool] = []
    monitor.stream_state_changed.connect(lambda _d, _s, connected, _m: states.append(connected))
    try:
        monitor.watch(WatchKey(None, "user", "a.service"))
        _wait(qapp, lambda: monitor.is_connected(None, "user"))
        assert states[0] is False and states[-1] is True
        assert len(calls) == 2
    finally:
        monitor.stop()


# --- Notifier ---


def test_notifier_sends_in_background_and_reports_failure(qapp: Any) -> None:
    sent: list[tuple[str, str]] = []
    DesktopNotifier(sender=lambda summary, body: sent.append((summary, body))).notify("t", "b")
    _wait(qapp, lambda: sent == [("t", "b")])

    def broken(_summary: str, _body: str) -> None:
        raise RuntimeError("no notification daemon")

    reasons: list[str] = []
    DesktopNotifier(sender=broken).notify("t", "b", on_failed=reasons.append)
    _wait(qapp, lambda: bool(reasons))
    assert "no notification daemon" in reasons[0]


async def test_send_notification_message_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    from types import SimpleNamespace

    from dbus_fast import MessageType

    from servicedeck.gui import notifications

    sent: list[Any] = []

    class FakeBus:
        def __init__(self, bus_type: Any) -> None:
            pass

        async def connect(self) -> "FakeBus":
            return self

        async def call(self, msg: Any) -> Any:
            sent.append(msg)
            return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=[7])

        def disconnect(self) -> None:
            sent.append("disconnected")

    monkeypatch.setattr("dbus_fast.aio.MessageBus", FakeBus)
    assert await notifications.send_notification("web failed", "on srv1") == 7
    msg = sent[0]
    assert (msg.interface, msg.member, msg.signature) == (
        "org.freedesktop.Notifications",
        "Notify",
        "susssasa{sv}i",
    )
    assert msg.body[3:5] == ["web failed", "on srv1"]
    assert msg.body[6]["urgency"].value == 2
    assert sent[-1] == "disconnected"


# --- GUI ---


def test_panel_shows_health(qapp: Any) -> None:
    from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel

    panel = ServiceDetailPanel()
    panel.show_service_details(_svc("web.service", "failed"), scope="user")
    now = time.time()
    panel.apply_health(
        ServiceResources(
            service="web.service",
            active_state="failed",
            n_restarts=3,
            result="exit-code",
            exec_main_code=1,
            exec_main_status=1,
            state_change_timestamp=int((now - 90) * 1_000_000),
        ),
        now=now,
    )
    assert panel._restarts_val.text() == "3"
    assert panel._last_exit_val.text() == "exited, status=1/FAILURE"
    assert panel._result_val.text() == "exit-code"
    assert panel._failed_since_val.text().startswith("1m ago")
    assert not panel._failed_since_val.isHidden()

    panel.apply_health(ServiceResources(service="web.service", active_state="active", n_restarts=0))
    assert panel._failed_since_val.isHidden()
    assert panel._last_exit_val.text() == "-"

    toggles: list[bool] = []
    panel.watch_toggled.connect(toggles.append)
    panel.set_watched(True)  # programmatic: no signal
    assert toggles == [] and panel.is_watched
    panel._watch_check.click()
    assert toggles == [False]


@pytest.fixture
def window(qapp: Any, client: MagicMock, tmp_path: Any) -> Any:
    from servicedeck.api_client.models.common import ScopeInfo
    from servicedeck.gui.views.main_window import MainWindow

    client.get_scope.return_value = ScopeInfo(active_scope="user")
    client.list_services.return_value = [_svc("web.service", "active")]
    client.list_devices.return_value = []
    client.get_unit_file.return_value = ServiceUnitFile(
        service="web.service", fragment_path="/x", content=""
    )
    client.get_logs.return_value = ServiceLogs(service="web.service", logs="")
    client.get_resources.return_value = ServiceResources(service="web.service")
    client.get_local_elevation.return_value = False
    client.watch_services.side_effect = lambda scope, device_id: ScriptedStream([])
    store = GuiPreferencesStore(tmp_path / "prefs.json")
    notifier = MagicMock(spec=DesktopNotifier)
    win = MainWindow(client=client, preferences_store=store, notifier=notifier)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()
    win.test_store = store
    win.test_notifier = notifier
    yield win
    win._watch_monitor.stop()
    win._stop_live_updates()
    win._detail_panel.stop_timers()


def test_watching_marks_row_and_persists(qapp: Any, window: Any) -> None:
    from servicedeck.gui.models.service_model import ServiceTableModel

    key = WatchKey(None, "user", "web.service")
    window._set_watched(key, True)

    index = window._table_model.index(0, 0)
    assert index.data(ServiceTableModel.ROLE_WATCHED) is True
    saved = window.test_store.load().watched_services
    assert [(w.device_id, w.scope, w.name) for w in saved] == [(None, "user", "web.service")]

    window._set_watched(key, False)
    assert index.data(ServiceTableModel.ROLE_WATCHED) is False
    assert window.test_store.load().watched_services == []


def test_watched_services_are_restored(qapp: Any, client: MagicMock, tmp_path: Any) -> None:
    from servicedeck.gui.preferences import GuiPreferences, WatchedService
    from servicedeck.gui.views.main_window import MainWindow

    store = GuiPreferencesStore(tmp_path / "prefs.json")
    store.save(
        GuiPreferences(
            watched_services=[WatchedService(device_id="srv1", scope="system", name="db.service")]
        )
    )
    client.list_services.return_value = []
    client.list_devices.return_value = []
    client.get_local_elevation.return_value = False
    client.watch_services.side_effect = lambda scope, device_id: ScriptedStream([])
    win = MainWindow(client=client, preferences_store=store, notifier=MagicMock())
    try:
        assert win._watch_monitor.watched == {WatchKey("srv1", "system", "db.service")}
        assert ("srv1", "system") in win._watch_monitor._groups
    finally:
        win._watch_monitor.stop()
        win._stop_live_updates()


def test_failure_sends_desktop_notification(qapp: Any, window: Any) -> None:
    key = WatchKey(None, "user", "web.service")
    window._on_watched_service_failed(key, _svc("web.service", "failed"))
    window.test_notifier.notify.assert_called_once()
    summary, body = window.test_notifier.notify.call_args.args[:2]
    assert summary == "web.service failed"
    assert "this computer, user scope" in body
    assert "failed" in window._status_label.text()

    window._notify_on_failure = False
    window._on_watched_service_failed(key, _svc("web.service", "failed"))
    assert window.test_notifier.notify.call_count == 1  # disabled in Preferences
