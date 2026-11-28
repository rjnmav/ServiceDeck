"""Search text and status chips reset when the host or scope changes."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.common import ScopeInfo
from servicedeck.api_client.models.remote import RemoteDevice
from servicedeck.api_client.models.service import Service


def _svc(name: str, active: str) -> Service:
    return Service(
        name=name,
        description=name,
        load_state="loaded",
        active_state=active,
        sub_state="running" if active == "active" else "dead",
        unit_file_state="enabled",
        scope="user",
    )


@pytest.fixture
def window(qapp: Any) -> Any:
    from servicedeck.gui.views.main_window import MainWindow

    client = MagicMock(spec=ServiceDeckClient)
    client.get_scope.return_value = ScopeInfo(active_scope="user")
    client.set_scope.return_value = ScopeInfo(active_scope="system")
    client.list_services.return_value = [_svc("a.service", "active"), _svc("b.service", "failed")]
    client.list_devices.return_value = [
        RemoteDevice(id="box", display_name="Box", hostname="box.local")
    ]
    client.get_local_elevation.return_value = False
    win = MainWindow(client=client)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()
    yield win
    win._stop_live_updates()
    win._detail_panel.stop_timers()


def _apply_filters(win: Any) -> None:
    win._toolbar.search_edit.setText("nginx")
    win._toolbar._chips["failed"].click()
    assert win._filter_model._name_filter == "nginx"
    assert win._filter_model._active_state_filter == "failed"
    assert win._toolbar._chips["failed"].isChecked()


def _assert_cleared(win: Any) -> None:
    assert win._toolbar.search_edit.text() == ""
    assert win._toolbar._chips[""].isChecked()
    assert not win._toolbar._chips["failed"].isChecked()
    assert win._filter_model._name_filter == ""
    assert win._filter_model._active_state_filter == ""


def test_host_change_clears_filters(qapp: Any, window: Any) -> None:
    _apply_filters(window)
    window._on_target_host_changed("box")
    _assert_cleared(window)


def test_selecting_the_same_host_keeps_filters(qapp: Any, window: Any) -> None:
    _apply_filters(window)
    window._on_target_host_changed(None)
    assert window._toolbar.search_edit.text() == "nginx"
    assert window._toolbar._chips["failed"].isChecked()


def test_scope_change_clears_filters(qapp: Any, window: Any) -> None:
    _apply_filters(window)
    window._on_system_scope_toggled(True)
    _assert_cleared(window)
