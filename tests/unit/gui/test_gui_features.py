"""Unit tests for new GUI components: ServiceDetailPanel, PreferencesDialog, CreateServiceDialog."""

from servicedeck.api_client.models.service import Service
from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog
from servicedeck.gui.views.dialogs.preferences_dialog import PreferencesDialog
from servicedeck.gui.views.service_detail_panel import (
    ServiceDetailPanel,
    format_bytes,
    format_duration,
    format_running_since,
)


def test_formatting_helpers():
    """Verify byte and duration formatters."""
    assert format_bytes(None) == "N/A"
    assert format_bytes(500) == "500 B"
    assert format_bytes(1024) == "1.0 KB"
    assert format_bytes(1048576) == "1.0 MB"
    assert format_bytes(1073741824) == "1.0 GB"

    assert format_duration(30) == "30s"
    assert format_duration(90) == "1m 30s"
    assert format_duration(3661) == "1h 1m 1s"
    assert format_duration(90061) == "1d 1h 1m 1s"

    assert format_running_since(None) == "N/A"
    assert format_running_since(0) == "N/A"
    assert ":" in format_running_since(1710000000000000)


def test_service_detail_panel_lifecycle(qapp):
    """Verify ServiceDetailPanel show, populate, and clear."""
    panel = ServiceDetailPanel()
    assert panel.windowTitle() == "Service Details"

    svc = Service(
        name="test-worker.service",
        description="A worker service",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
        scope="user",
    )

    panel.show_service_details(svc, scope="user")
    assert panel._name_val.text() == "test-worker.service"
    assert panel._desc_val.text() == "A worker service"
    assert panel._active_val.text() == "ACTIVE"
    assert panel._enabled_val.text() == "ENABLED"

    panel.clear()
    assert panel._name_val.text() == "-"
    assert panel._desc_val.text() == "-"
    assert panel._unit_file_edit.toPlainText() == ""
    assert panel._log_edit.toPlainText() == ""


def test_preferences_dialog_signals(qapp):
    """Verify PreferencesDialog emits preferences_changed."""
    dlg = PreferencesDialog(current_theme="dark", log_interval=10, res_interval=4)
    assert dlg.log_interval == 10
    assert dlg.resource_interval == 4

    received = []
    dlg.preferences_changed.connect(
        lambda theme, log_i, res_i: received.append((theme, log_i, res_i))
    )

    dlg._log_spin.setValue(15)
    dlg._res_spin.setValue(5)
    dlg._on_apply()

    assert len(received) == 1
    assert received[0] == ("dark", 15, 5)


def test_create_service_dialog_form_sync(qapp):
    """Verify CreateServiceDialog syncs form inputs to unit editor."""
    dlg = CreateServiceDialog(default_scope="user")
    dlg._name_edit.setText("myapp")
    dlg._desc_edit.setText("My Application")
    dlg._exec_edit.setText("/usr/bin/myapp")

    text = dlg._editor.toPlainText()
    assert "Description=My Application" in text
    assert "ExecStart=/usr/bin/myapp" in text
    assert "[Install]" in text
    assert dlg._user_radio.isChecked()
    assert dlg.fileName() == "myapp"
    assert not dlg.isSystemScope()


def test_create_service_dialog_two_way_sync(qapp):
    """Verify editing the raw unit file syncs back into the form widgets."""
    dlg = CreateServiceDialog(default_scope="system")
    assert dlg.isSystemScope()

    new_unit_text = (
        "[Unit]\n"
        "Description=Direct Edited Description\n\n"
        "[Service]\n"
        "Type=forking\n"
        "ExecStart=/usr/local/bin/daemon\n"
        "Restart=always\n\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )
    dlg._content_edit.setPlainText(new_unit_text)

    assert dlg._desc_edit.text() == "Direct Edited Description"
    assert dlg._exec_edit.text() == "/usr/local/bin/daemon"
    assert dlg._type_combo.currentText() == "forking"
    assert dlg._restart_combo.currentText() == "always"
