"""Unit tests for remote host GUI components and integration."""

from typing import Any
from unittest.mock import MagicMock

from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.common import ScopeInfo
from servicedeck.api_client.models.remote import RemoteDevice
from servicedeck.api_client.models.service import Service
from servicedeck.gui.views.dialogs.add_remote_device_dialog import AddRemoteDeviceDialog
from servicedeck.gui.views.dialogs.manage_remote_devices_dialog import (
    ManageRemoteDevicesDialog,
)
from servicedeck.gui.views.host_sidebar import HostSidebar
from servicedeck.gui.views.main_window import MainWindow
from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel
from servicedeck.gui.views.service_toolbar import ServiceToolbar


def test_host_sidebar_selector_and_signals(qapp):
    """Verify HostSidebar host list, scope toggle, and signals."""
    sidebar = HostSidebar()
    devices = [
        RemoteDevice(
            id="web-server",
            hostname="192.168.1.50",
            port=22,
            username="ubuntu",
            display_name="Production Web",
            connected=True,
        ),
        RemoteDevice(
            id="db-server",
            hostname="192.168.1.60",
            port=2222,
            username="postgres",
            display_name="Database Node",
            connected=False,
        ),
    ]

    sidebar.set_hosts(devices, current_device_id="web-server")
    assert len(sidebar._host_rows) == 3  # Local + 2 remote devices

    host_changes = []
    add_requests = []
    scope_changes = []

    sidebar.target_host_changed.connect(host_changes.append)
    sidebar.add_host_requested.connect(lambda: add_requests.append(True))
    sidebar.scope_toggled.connect(scope_changes.append)

    sidebar._select_host("db-server")
    assert host_changes == ["db-server"]

    sidebar._select_host(None)
    assert host_changes == ["db-server", None]

    sidebar._add_host_btn.click()
    assert add_requests == [True]

    sidebar.system_scope_button.setChecked(True)
    assert scope_changes == [True]


def test_service_toolbar_filter_chips_and_counts(qapp):
    """Verify ServiceToolbar filter chips update counts and emit state filters."""
    toolbar = ServiceToolbar()
    toolbar.update_counts({"all": 10, "active": 6, "failed": 1, "inactive": 3})

    assert "10" in toolbar._chips[""].text()
    assert "6" in toolbar._chips["active"].text()
    assert "1" in toolbar._chips["failed"].text()
    assert "3" in toolbar._chips["inactive"].text()

    filters = []
    toolbar.active_state_filter_changed.connect(filters.append)

    toolbar._chips["failed"].click()
    toolbar._chips[""].click()
    assert filters == ["failed", ""]


def test_add_remote_device_dialog_ui_and_id_gen(qapp):
    """Verify AddRemoteDeviceDialog fields, device ID generation, and validation."""
    dlg = AddRemoteDeviceDialog()
    assert dlg.windowTitle() == "Add Remote Linux Host"

    assert dlg._generate_device_id("192.168.1.100") == "192-168-1-100"
    assert dlg._generate_device_id("server.internal.company.com") == "server-internal-company-com"

    # Typing host auto-suggests display name placeholder
    dlg._host_edit.setText("alpha.server")
    assert dlg._name_edit.placeholderText() == "alpha.server"


def test_manage_remote_devices_dialog_table_population(qapp):
    """Verify ManageRemoteDevicesDialog lists remote devices and toggles buttons."""
    mock_client = MagicMock(spec=ServiceDeckClient)
    mock_client.list_devices.return_value = [
        RemoteDevice(
            id="dev-1",
            hostname="host1.local",
            port=22,
            username="admin",
            display_name="Host 1",
            connected=True,
        ),
        RemoteDevice(
            id="dev-2",
            hostname="host2.local",
            port=22,
            username="root",
            display_name="Host 2",
            connected=False,
        ),
    ]

    dlg = ManageRemoteDevicesDialog(client=mock_client)
    # The device list loads on a QThreadPool worker; its result reaches the dialog through a
    # queued signal. Wait for the worker, then deliver the queued events.
    for _ in range(50):
        if dlg._table.rowCount():
            break
        QThreadPool.globalInstance().waitForDone(100)
        qapp.processEvents()

    assert dlg._table.rowCount() == 2
    assert dlg._table.item(0, 0).text() == "Host 1"
    assert dlg._table.item(0, 1).text() == "host1.local"
    assert "Connected" in dlg._table.item(0, 4).text()

    assert dlg._table.item(1, 0).text() == "Host 2"
    assert "Offline" in dlg._table.item(1, 4).text()

    # Initially no selection
    assert not dlg._switch_btn.isEnabled()
    assert not dlg._connect_btn.isEnabled()
    assert not dlg._disconnect_btn.isEnabled()
    assert not dlg._remove_btn.isEnabled()

    # Select row 0
    dlg._table.selectRow(0)
    assert dlg._switch_btn.isEnabled()
    assert dlg._connect_btn.isEnabled()
    assert dlg._disconnect_btn.isEnabled()
    assert dlg._remove_btn.isEnabled()

    # Select row 1
    dlg._table.selectRow(1)
    assert dlg._switch_btn.isEnabled()
    assert dlg._connect_btn.isEnabled()
    assert dlg._disconnect_btn.isEnabled()
    assert dlg._remove_btn.isEnabled()

    # Click switch button
    dlg._on_switch_clicked()
    assert dlg.selected_device_id == "dev-2"


def test_detail_panel_remote_device_id(qapp):
    """Verify ServiceDetailPanel remembers current remote device_id."""
    mock_client = MagicMock(spec=ServiceDeckClient)
    panel = ServiceDetailPanel(client=mock_client)

    svc = Service(
        name="remote-worker.service",
        description="Remote worker",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
        scope="user",
    )

    panel.show_service_details(svc, scope="user", device_id="node-xyz")
    assert panel._current_device_id == "node-xyz"
    assert panel._current_service.name == "remote-worker.service"


def test_main_window_remote_host_handling(qapp):
    """Verify MainWindow integrates host selector and updates title/status."""
    from servicedeck.api_client.models.service import (
        ServiceLogs,
        ServiceResources,
        ServiceUnitFile,
    )

    mock_client = MagicMock(spec=ServiceDeckClient)
    mock_client.get_scope.return_value = ScopeInfo(
        active_scope="user", available_scopes=["user", "system"]
    )
    mock_client.list_devices.return_value = [
        RemoteDevice(
            id="remote-box",
            hostname="box.local",
            port=22,
            username="user",
            display_name="My Box",
            connected=True,
        )
    ]
    mock_client.list_services.return_value = [
        Service(
            name="app.service",
            description="App",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            scope="user",
        )
    ]
    mock_client.get_unit_file.return_value = ServiceUnitFile(
        service="app.service",
        content="[Unit]",
        fragment_path="/etc/systemd/system/app.service",
        scope="user",
    )
    mock_client.get_logs.return_value = ServiceLogs(
        service="app.service", logs="sample logs", scope="user", lines=200
    )
    mock_client.get_resources.return_value = ServiceResources(
        service="app.service",
        cpu_usage_nsec=0,
        memory_current_bytes=1024,
        active_state="active",
        scope="user",
    )

    win = MainWindow(client=mock_client)
    qapp.processEvents()

    assert win._current_device_id is None
    assert "Local" in win.windowTitle()

    # Switch to remote host
    win._devices = mock_client.list_devices.return_value
    win._on_target_host_changed("remote-box")
    qapp.processEvents()

    assert win._current_device_id == "remote-box"
    assert "My Box" in win.windowTitle()

    # Check display name helper
    assert "My Box (box.local)" in win._get_host_display_name()

    # Switch back to local
    win._on_target_host_changed(None)
    assert win._current_device_id is None
    assert "Local" in win.windowTitle()


def test_main_window_scope_toggle_remote(qapp):
    """Verify MainWindow toggles scope cleanly on remote host without race conditions."""
    mock_client = MagicMock(spec=ServiceDeckClient)
    mock_client.get_scope.return_value = ScopeInfo(
        active_scope="user", available_scopes=["user", "system"]
    )
    mock_client.list_devices.return_value = []
    mock_client.list_services.return_value = [
        Service(
            name="cron.service",
            description="Cron",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            scope="system",
        )
    ]

    win = MainWindow(client=mock_client)
    qapp.processEvents()

    win._current_device_id = "remote-node"
    win._on_system_scope_toggled(True)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()

    assert win._current_scope == "system"
    mock_client.list_services.assert_called_with(scope="system", device_id="remote-node")


def test_add_remote_device_dialog_agent_mode_defaults_to_bundled(qapp: Any) -> None:
    dlg = AddRemoteDeviceDialog()
    assert dlg._agent_mode_combo.currentData() == "bundled"
    modes = [dlg._agent_mode_combo.itemData(i) for i in range(dlg._agent_mode_combo.count())]
    assert modes == ["bundled", "installed", "auto"]


def test_add_remote_device_dialog_inline_validation_non_shifting(qapp: Any) -> None:
    dlg = AddRemoteDeviceDialog()
    assert dlg._banner_stack.currentIndex() == 0

    dlg._on_test_connection_clicked()
    assert dlg._banner_stack.currentIndex() == 1
    assert "Host / IP" in dlg._status_banner.text()

    dlg._host_edit.setText("10.0.0.5")
    assert dlg._banner_stack.currentIndex() == 0
