"""GUI tests for live updates (table rows updated in place) and followed logs."""

import queue
import time
from collections.abc import Callable, Iterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.exceptions import ServiceDeckHTTPError
from servicedeck.api_client.models.common import ScopeInfo
from servicedeck.api_client.models.service import Service, ServiceEvent, ServiceLogs
from servicedeck.gui.models.service_model import ServiceTableModel
from servicedeck.gui.views.main_window import MainWindow
from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel
from servicedeck.gui.workers.stream_worker import StreamWorker

_END = object()


class FakeStream:
    """Behaves like ``EventStream``: blocks for items until fed, ended or closed."""

    def __init__(self) -> None:
        self._items: queue.Queue[Any] = queue.Queue()
        self.closed = False

    def feed(self, *items: Any) -> None:
        for item in items:
            self._items.put(item)

    def end(self) -> None:
        self._items.put(_END)

    def __iter__(self) -> Iterator[Any]:
        while not self.closed:
            item = self._items.get()
            if item is _END or self.closed:
                return
            if isinstance(item, Exception):
                raise item
            yield item

    def close(self) -> None:
        self.closed = True
        self._items.put(_END)


def wait_until(qapp: Any, condition: Callable[[], bool], timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        qapp.processEvents()
        if condition():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")


def svc(name: str, active: str = "active", sub: str = "running", desc: str = "Desc") -> Service:
    return Service(
        name=name,
        description=desc,
        load_state="loaded",
        active_state=active,
        sub_state=sub,
        unit_file_state="enabled",
        scope="user",
    )


# --- ServiceTableModel ---


def test_model_updates_rows_in_place_and_highlights_state_changes(qapp: Any) -> None:
    model = ServiceTableModel()
    model.set_services([svc("a.service"), svc("b.service")])
    changed: list[int] = []
    model.dataChanged.connect(lambda top, _bottom, *_: changed.append(top.row()))

    previous, current = model.apply_service_change(svc("b.service", "failed", "failed", desc=""))

    assert previous == svc("b.service")
    assert current.description == "Desc"  # kept: live events may carry none
    assert model.rowCount() == 2
    assert changed == [1]
    assert model.is_highlighted("b.service")
    background = model.data(model.index(1, 0), 8)  # BackgroundRole
    assert background == ServiceTableModel.HIGHLIGHT_FAILED

    # An identical state is not a change.
    changed.clear()
    model.apply_service_change(svc("a.service"))
    assert changed == []
    assert not model.is_highlighted("a.service")


def test_model_adds_removes_and_merges_without_reset(qapp: Any) -> None:
    model = ServiceTableModel()
    model.set_services([svc("a.service"), svc("b.service")])
    resets: list[bool] = []
    model.modelReset.connect(lambda: resets.append(True))

    model.apply_service_change(svc("c.service"))
    assert model.row_of("c.service") == 2
    assert model.remove_service("a.service") == svc("a.service")
    assert model.row_of("b.service") == 0

    changes = model.merge_services([svc("b.service", "inactive", "dead"), svc("d.service")])
    assert [s.name for s in model.all_services()] == ["b.service", "d.service"]
    assert {current.name for _, current in changes} == {"b.service", "d.service"}
    assert resets == []


def test_model_highlights_expire(qapp: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    model = ServiceTableModel()
    model.set_services([svc("a.service")])
    monkeypatch.setattr(ServiceTableModel, "HIGHLIGHT_SECONDS", 0.0)
    model.apply_service_change(svc("a.service", "inactive", "dead"))
    assert model.is_highlighted("a.service")
    model.expire_highlights()
    assert not model.is_highlighted("a.service")
    assert model.data(model.index(0, 0), 8) is None


# --- StreamWorker ---


def test_stream_worker_emits_items_and_stops(qapp: Any) -> None:
    stream = FakeStream()
    worker = StreamWorker(lambda: stream)
    items: list[Any] = []
    finished: list[int] = []
    worker.signals.item.connect(lambda token, item: items.append((token, item)))
    worker.signals.finished.connect(finished.append)
    worker.start()

    stream.feed("a", "b")
    wait_until(qapp, lambda: len(items) == 2)
    assert items == [(worker.token, "a"), (worker.token, "b")]

    worker.stop()
    wait_until(qapp, lambda: finished == [worker.token])
    assert stream.closed


def test_stream_worker_reports_failure(qapp: Any) -> None:
    def refuse() -> FakeStream:
        raise ServiceDeckHTTPError(404, "no such endpoint")

    worker = StreamWorker(refuse)
    failures: list[str] = []
    worker.signals.failed.connect(lambda _token, msg, _exc: failures.append(msg))
    worker.start()
    wait_until(qapp, lambda: failures == ["no such endpoint"])


# --- MainWindow live updates ---


@pytest.fixture
def live_client() -> MagicMock:
    client = MagicMock(spec=ServiceDeckClient)
    client.get_scope.return_value = ScopeInfo(active_scope="user", available_scopes=["user"])
    client.list_devices.return_value = []
    client.list_services.return_value = [svc("a.service"), svc("b.service")]
    client.streams = []

    def watch(scope: str | None = None, device_id: str | None = None) -> FakeStream:
        stream = FakeStream()
        stream.args = (scope, device_id)  # type: ignore[attr-defined]
        client.streams.append(stream)
        return stream

    client.watch_services.side_effect = watch
    return client


def _loaded_window(qapp: Any, client: MagicMock) -> MainWindow:
    win = MainWindow(client=client)
    # Keep the post-"ready" re-list out of the way; it is exercised separately.
    win._resync_timer.setInterval(60_000)
    wait_until(qapp, lambda: win._table_model.rowCount() == 2 and len(client.streams) == 1)
    return win


def test_main_window_applies_live_events(qapp: Any, live_client: MagicMock) -> None:
    win = _loaded_window(qapp, live_client)
    stream = live_client.streams[0]
    assert stream.args == ("user", None)
    assert not win.live_updates_connected

    stream.feed(ServiceEvent(kind="ready", scope="user"))
    wait_until(qapp, lambda: win.live_updates_connected)
    assert "Live" in win._live_label.text()

    stream.feed(
        ServiceEvent(
            kind="changed",
            scope="user",
            name="b.service",
            service=svc("b.service", "failed", "failed"),
        ),
        ServiceEvent(kind="changed", scope="user", name="new.service", service=svc("new.service")),
        ServiceEvent(kind="removed", scope="user", name="a.service"),
    )
    model = win._table_model
    wait_until(qapp, lambda: model.row_of("a.service") is None)
    b_service = model.service_by_name("b.service")
    assert b_service is not None
    assert b_service.is_failed
    assert model.row_of("new.service") is not None
    assert "b.service failed" in win._status_label.text()
    assert win._count_label.text() == "2 services"
    win.close()
    QThreadPool.globalInstance().waitForDone(2000)


def test_main_window_relists_in_place_after_ready(qapp: Any, live_client: MagicMock) -> None:
    win = _loaded_window(qapp, live_client)
    win._table_view.selectRow(0)
    selected = win._selected_service_name()
    live_client.list_services.return_value = [
        svc("a.service", "failed", "failed"),
        svc("b.service"),
    ]

    win._resync_timer.setInterval(0)
    live_client.streams[0].feed(ServiceEvent(kind="ready", scope="user"))
    wait_until(qapp, lambda: win._table_model.service_by_name("a.service").is_failed)  # type: ignore[union-attr]
    assert win._selected_service_name() == selected  # no reset: selection survives
    win.close()
    QThreadPool.globalInstance().waitForDone(2000)


def test_main_window_restarts_stream_for_new_host(qapp: Any, live_client: MagicMock) -> None:
    win = _loaded_window(qapp, live_client)
    first = live_client.streams[0]

    win._on_target_host_changed("srv1")
    assert first.closed
    wait_until(qapp, lambda: len(live_client.streams) == 2)
    assert live_client.streams[1].args == ("user", "srv1")
    win.close()
    assert live_client.streams[1].closed
    QThreadPool.globalInstance().waitForDone(2000)


def test_main_window_retries_after_stream_failure(qapp: Any, live_client: MagicMock) -> None:
    win = _loaded_window(qapp, live_client)
    live_client.streams[0].feed(ServiceDeckHTTPError(502, "agent gone"))
    wait_until(qapp, lambda: win._live_retry_timer.isActive())
    assert not win.live_updates_connected
    assert "agent gone" in win._live_label.toolTip()

    win._live_retry_timer.setInterval(0)
    win._live_retry_timer.start(0)
    wait_until(qapp, lambda: len(live_client.streams) == 2)
    win.close()
    QThreadPool.globalInstance().waitForDone(2000)


# --- Followed logs in the detail panel ---


@pytest.fixture
def log_client() -> MagicMock:
    client = MagicMock(spec=ServiceDeckClient)
    client.log_streams = []

    def follow(name: str, **_kwargs: Any) -> FakeStream:
        stream = FakeStream()
        client.log_streams.append(stream)
        return stream

    client.follow_logs.side_effect = follow
    client.get_logs.return_value = ServiceLogs(service="a.service", logs="polled one\npolled two")
    return client


def test_detail_panel_follows_logs_with_filter_and_pause(qapp: Any, log_client: MagicMock) -> None:
    panel = ServiceDetailPanel(client=log_client)
    panel.show_service_details(svc("a.service"), scope="user")
    wait_until(qapp, lambda: len(log_client.log_streams) == 1)
    assert panel.is_following_logs
    stream = log_client.log_streams[0]

    stream.feed("Started a", "error: disk full", "all good")
    wait_until(qapp, lambda: "all good" in panel._log_edit.toPlainText())
    assert panel._log_status.text() == "Following"

    panel._log_filter_edit.setText("ERROR")
    assert panel._log_edit.toPlainText() == "error: disk full"
    stream.feed("another error")
    wait_until(qapp, lambda: "another error" in panel._log_edit.toPlainText())
    assert "all good" not in panel._log_edit.toPlainText()
    panel._log_filter_edit.setText("")
    assert panel._log_edit.toPlainText().count("\n") == 3

    panel._follow_check.setChecked(False)
    assert stream.closed
    assert not panel.is_following_logs
    assert panel._log_status.text() == "Paused"

    panel._follow_check.setChecked(True)
    wait_until(qapp, lambda: len(log_client.log_streams) == 2)
    panel.clear()
    assert log_client.log_streams[1].closed
    QThreadPool.globalInstance().waitForDone(2000)


def test_detail_panel_falls_back_to_polling(qapp: Any, log_client: MagicMock) -> None:
    log_client.follow_logs.side_effect = ServiceDeckHTTPError(404, "Not Found")
    panel = ServiceDetailPanel(client=log_client)
    panel.show_service_details(svc("a.service"), scope="user")

    wait_until(qapp, lambda: "polled two" in panel._log_edit.toPlainText())
    assert not panel.is_following_logs
    assert panel._log_status.text().startswith("Polling")
    assert "Not Found" in panel._log_status.toolTip()
    assert panel._log_timer.isActive()
    panel.clear()
    QThreadPool.globalInstance().waitForDone(2000)
