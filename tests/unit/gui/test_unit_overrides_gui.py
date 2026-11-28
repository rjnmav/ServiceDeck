"""GUI: unit file tab with drop-ins, the override editor, revert, and local admin access."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool
from PySide6.QtWidgets import QDialog, QMessageBox

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.exceptions import ServiceDeckHTTPError
from servicedeck.api_client.models.service import (
    DropInFile,
    OverrideResult,
    RevertResult,
    Service,
    ServiceLogs,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.gui.views.dialogs import remote_onboarding
from servicedeck.gui.views.dialogs.edit_override_dialog import (
    OVERRIDE_SKELETON,
    EditOverrideDialog,
)
from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel

OVERRIDE = "/etc/systemd/system/ssh.service.d/override.conf"

SSH = Service(
    name="ssh.service",
    description="OpenSSH",
    load_state="loaded",
    active_state="active",
    sub_state="running",
    unit_file_state="enabled",
    scope="system",
)

UNIT = ServiceUnitFile(
    service="ssh.service",
    fragment_path="/usr/lib/systemd/system/ssh.service",
    content="[Unit]\nDescription=OpenSSH\n[Service]\nExecStart=/usr/bin/sshd -D\n",
    scope="system",
    drop_ins=(
        DropInFile("/usr/lib/systemd/system/ssh.service.d/10-vendor.conf", "[Service]\nA=1\n"),
        DropInFile(OVERRIDE, "[Service]\nNice=5\n", editable=True),
    ),
    override_path=OVERRIDE,
    need_daemon_reload=True,
)

PLAIN_UNIT = ServiceUnitFile(
    service="ssh.service",
    fragment_path="/usr/lib/systemd/system/ssh.service",
    content="[Unit]\nDescription=OpenSSH\n",
    scope="system",
    override_path=OVERRIDE,
)


def _http_error(error_type: str, status: int, **details: Any) -> ServiceDeckHTTPError:
    return ServiceDeckHTTPError(status, f"{error_type} happened", error_type, details)


def _wait(qapp: Any, condition: Any) -> None:
    for _ in range(50):
        if condition():
            return
        QThreadPool.globalInstance().waitForDone(200)
        qapp.processEvents()
    raise AssertionError("condition not reached")


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=ServiceDeckClient)


# --- Unit File tab ---


def test_panel_shows_fragment_and_drop_ins(qapp: Any) -> None:
    panel = ServiceDetailPanel()
    panel.show_service_details(SSH, scope="system")
    assert not panel._edit_override_btn.isEnabled()  # nothing loaded yet

    panel.set_unit_file(UNIT)

    text = panel._unit_file_edit.toPlainText()
    assert text.index("# /usr/lib/systemd/system/ssh.service") < text.index(f"# {OVERRIDE}")
    assert "Nice=5" in text
    assert "2 drop-ins (1 override)" in panel._unit_path_hint.text()
    assert not panel._unit_reload_warning.isHidden()
    assert panel._edit_override_btn.isEnabled()
    assert panel._revert_unit_btn.isEnabled()

    panel.set_actions_enabled(False)
    assert not panel._edit_override_btn.isEnabled()
    assert not panel._revert_unit_btn.isEnabled()
    panel.set_actions_enabled(True)

    panel.set_unit_file(PLAIN_UNIT)
    assert panel._unit_file_edit.toPlainText() == PLAIN_UNIT.content
    assert panel._edit_override_btn.isEnabled()
    assert not panel._revert_unit_btn.isEnabled()  # nothing to revert

    panel.clear()
    assert panel.current_unit_file is None
    assert not panel._edit_override_btn.isEnabled()


def test_panel_buttons_emit_signals(qapp: Any) -> None:
    panel = ServiceDetailPanel()
    panel.show_service_details(SSH, scope="system")
    panel.set_unit_file(UNIT)
    seen: list[str] = []
    panel.edit_override_requested.connect(lambda: seen.append("edit"))
    panel.revert_requested.connect(lambda: seen.append("revert"))
    panel._edit_override_btn.click()
    panel._revert_unit_btn.click()
    assert seen == ["edit", "revert"]


# --- Override editor ---


def test_editor_prefills_override_and_shows_reference(qapp: Any) -> None:
    dlg = EditOverrideDialog(unit=UNIT, scope="system")
    assert dlg.editor.toPlainText() == "[Service]\nNice=5\n"
    reference = dlg._current_view.toPlainText()
    assert "ExecStart=/usr/bin/sshd -D" in reference
    assert "10-vendor.conf" in reference
    assert OVERRIDE not in reference  # the file being edited is on the right only


def test_editor_starts_from_skeleton_without_override(qapp: Any) -> None:
    dlg = EditOverrideDialog(unit=PLAIN_UNIT, scope="system")
    assert dlg.editor.toPlainText() == OVERRIDE_SKELETON
    assert dlg._save_btn.isEnabled()


def test_editor_live_validation(qapp: Any) -> None:
    dlg = EditOverrideDialog(unit=UNIT, scope="system")

    dlg.editor.setPlainText("Nice=5\n")
    assert not dlg._save_btn.isEnabled()
    assert "inside a section" in dlg.banner_text()

    dlg.editor.setPlainText("[Servcie]\nNice=5\n")
    assert dlg._save_btn.isEnabled()
    assert "unknown section" in dlg.banner_text()

    dlg.editor.setPlainText("# nothing\n")
    assert dlg._save_btn.isEnabled()
    assert "removes the override" in dlg.banner_text()

    dlg.editor.setPlainText("[Service]\nNice=7\n")
    assert dlg.banner_text() == ""


def test_save_writes_override(qapp: Any, client: MagicMock) -> None:
    result = OverrideResult("ssh.service", "user", OVERRIDE, load_state="loaded")
    client.write_override.return_value = result
    dlg = EditOverrideDialog(client=client, unit=UNIT, scope="user")
    dlg.editor.setPlainText("[Service]\nNice=7\n")
    dlg._on_save()
    _wait(qapp, lambda: dlg.result() == QDialog.DialogCode.Accepted)

    assert dlg.result_override == result
    client.write_override.assert_called_once_with(
        "ssh.service", "[Service]\nNice=7\n", scope="user", device_id=None
    )


def test_unchanged_override_is_not_written(qapp: Any, client: MagicMock) -> None:
    dlg = EditOverrideDialog(client=client, unit=UNIT, scope="user")
    dlg._on_save()
    assert dlg.result() == QDialog.DialogCode.Rejected
    client.write_override.assert_not_called()


def test_rejected_override_keeps_dialog_open_with_error(qapp: Any, client: MagicMock) -> None:
    client.write_override.side_effect = _http_error("ServiceOperationError", 400)
    dlg = EditOverrideDialog(client=client, unit=UNIT, scope="user")
    dlg.editor.setPlainText("[Service]\nType=bogus\n")
    dlg._on_save()
    _wait(qapp, lambda: "happened" in dlg.banner_text())

    assert dlg.result() != QDialog.DialogCode.Accepted
    assert dlg._save_btn.isEnabled()
    assert not dlg.editor.isReadOnly()


def test_local_system_save_asks_for_sudo_then_retries(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    result = OverrideResult("ssh.service", "system", OVERRIDE, load_state="loaded")
    client.write_override.side_effect = [
        _http_error("LocalElevationRequiredError", 403, device_id=None),
        result,
    ]
    client.elevate_local.side_effect = [
        _http_error("RemoteSudoAuthError", 401, password_required=True),
        True,
    ]
    targets: list[str] = []

    def ask(_parent: Any, target: str, _retry: str | None) -> str:
        targets.append(target)
        return "pw"

    monkeypatch.setattr(remote_onboarding, "ask_sudo_password", ask)
    elevated: list[bool] = []
    dlg = EditOverrideDialog(
        client=client, unit=UNIT, scope="system", on_elevated=lambda: elevated.append(True)
    )
    dlg.editor.setPlainText("[Service]\nNice=7\n")
    dlg._on_save()
    _wait(qapp, lambda: dlg.result() == QDialog.DialogCode.Accepted)

    assert targets == [remote_onboarding.LOCAL_TARGET]
    assert [c.args for c in client.elevate_local.call_args_list] == [(None,), ("pw",)]
    client.elevate_device.assert_not_called()
    assert elevated == [True]
    assert client.write_override.call_count == 2


def test_local_sudo_prompt_text(monkeypatch: pytest.MonkeyPatch, qapp: Any) -> None:
    from PySide6.QtWidgets import QInputDialog

    labels: list[str] = []

    def fake_get_text(_parent: Any, _title: str, label: str, _mode: Any) -> tuple[str, bool]:
        labels.append(label)
        return "pw", True

    monkeypatch.setattr(QInputDialog, "getText", fake_get_text)
    assert remote_onboarding.ask_sudo_password(None, remote_onboarding.LOCAL_TARGET, None) == "pw"
    assert "this computer" in labels[0]
    assert "system unit files" in labels[0]


# --- Main window ---


@pytest.fixture
def window(qapp: Any, client: MagicMock) -> Any:
    from servicedeck.gui.views.main_window import MainWindow

    client.list_services.return_value = [SSH]
    client.list_devices.return_value = []
    client.get_unit_file.return_value = UNIT
    client.get_logs.return_value = ServiceLogs(service="ssh.service", logs="", scope="system")
    client.get_resources.return_value = ServiceResources(service="ssh.service", scope="system")
    client.get_local_elevation.return_value = False
    win = MainWindow(client=client)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()
    win._current_scope = "system"
    win._detail_panel.show_service_details(SSH, scope="system")
    win._detail_panel.set_unit_file(UNIT)
    yield win
    win._stop_live_updates()
    win._detail_panel.stop_timers()


def test_revert_confirms_then_asks_for_local_admin_and_shows_pill(
    qapp: Any, window: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = []

    def confirm(_parent: Any, _title: str, text: str, *_args: Any) -> Any:
        asked.append(text)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", confirm)
    monkeypatch.setattr(remote_onboarding, "ask_sudo_password", lambda *_: "pw")
    client.revert_overrides.side_effect = [
        _http_error("LocalElevationRequiredError", 403, device_id=None),
        RevertResult("ssh.service", "system", (OVERRIDE,)),
    ]
    client.elevate_local.side_effect = [
        _http_error("RemoteSudoAuthError", 401, password_required=True),
        True,
    ]

    window._on_revert_requested()
    _wait(qapp, lambda: client.revert_overrides.call_count == 2 and not window._is_busy)

    assert OVERRIDE in asked[0]
    assert "10-vendor.conf" not in asked[0]
    assert client.revert_overrides.call_args.kwargs == {"scope": "system", "device_id": None}
    assert None in window._elevated_devices
    assert window._sidebar.admin_button.isVisibleTo(window)
    assert "this computer" in window._sidebar.admin_button.toolTip()


def test_revert_cancelled_does_nothing(
    qapp: Any, window: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(QMessageBox, "warning", lambda *_a: QMessageBox.StandardButton.No)
    window._on_revert_requested()
    client.revert_overrides.assert_not_called()


def test_drop_local_admin(qapp: Any, window: Any, client: MagicMock) -> None:
    window._elevated_devices.add(None)
    window._update_admin_indicator()
    window._on_drop_admin_clicked()
    _wait(qapp, lambda: None not in window._elevated_devices)
    client.drop_local_elevation.assert_called_once()
    client.drop_device_privileges.assert_not_called()
    assert not window._sidebar.admin_button.isVisibleTo(window)


def test_local_admin_state_is_synced_from_backend(
    qapp: Any, window: Any, client: MagicMock
) -> None:
    client.get_local_elevation.return_value = True
    window._sync_local_admin_state()
    _wait(qapp, lambda: None in window._elevated_devices)
    client.get_local_elevation.return_value = False
    window._sync_local_admin_state()
    _wait(qapp, lambda: None not in window._elevated_devices)
