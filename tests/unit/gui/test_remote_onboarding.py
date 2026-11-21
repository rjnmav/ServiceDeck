"""GUI onboarding flow: trust host key, set up SSH key login, then connect."""

from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.exceptions import ServiceDeckHTTPError
from servicedeck.api_client.models.remote import (
    HostKeyInfo,
    KeySetupInfo,
    RemoteConnectionInfo,
    RemoteDevice,
)
from servicedeck.gui.views.dialogs import remote_onboarding


def _http_error(error_type: str, status: int, **details: Any) -> ServiceDeckHTTPError:
    return ServiceDeckHTTPError(status, f"{error_type} happened", error_type, details)


def _run_until(qapp: Any, done: dict[str, Any]) -> None:
    for _ in range(50):
        if done:
            return
        QThreadPool.globalInstance().waitForDone(1000)
        qapp.processEvents()
    raise AssertionError("onboarding flow did not finish")


@pytest.fixture
def client() -> MagicMock:
    return MagicMock(spec=ServiceDeckClient)


def test_full_onboarding_trusts_host_sets_up_key_and_connects(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    connected = RemoteConnectionInfo(device_id="srv", connected=True, remote_host="srv")
    client.connect_device.side_effect = [
        _http_error("RemoteHostKeyUnknownError", 409, fingerprint="SHA256:abc", hostname="srv"),
        _http_error("SSHAuthenticationError", 401),
        connected,
    ]
    client.trust_host_key.return_value = HostKeyInfo(
        "srv", 22, "trusted", "ssh-ed25519", "SHA256:abc"
    )
    installed = KeySetupInfo(
        device=RemoteDevice(id="srv", display_name="srv", hostname="srv"),
        key_path="/k/id_ed25519",
        key_fingerprint="SHA256:key",
        added=True,
    )
    client.setup_key.side_effect = [_http_error("SSHAuthenticationError", 401), installed]

    prompts: list[str | None] = []
    passwords = iter(["wrong", "right"])
    monkeypatch.setattr(remote_onboarding, "confirm_host_key", lambda _p, info: True)

    def fake_ask_password(_parent: Any, target: str, retry_message: str | None) -> str:
        prompts.append(retry_message)
        return next(passwords)

    monkeypatch.setattr(remote_onboarding, "ask_password", fake_ask_password)

    done: dict[str, Any] = {}
    keys: list[KeySetupInfo] = []
    remote_onboarding.connect_with_onboarding(
        None,
        client,
        "srv",
        target="alice@srv",
        on_success=lambda info: done.setdefault("ok", info),
        on_error=lambda msg, exc: done.setdefault("error", msg),
        on_key_installed=keys.append,
    )
    _run_until(qapp, done)

    assert done == {"ok": connected}
    client.trust_host_key.assert_called_once_with("srv", "SHA256:abc")
    assert [c.args for c in client.setup_key.call_args_list] == [("srv", "wrong"), ("srv", "right")]
    assert prompts == [None, "The password was not accepted."]
    assert keys == [installed]


def test_declining_host_key_stops_without_contacting_setup(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.connect_device.side_effect = _http_error(
        "RemoteHostKeyUnknownError", 409, fingerprint="SHA256:abc"
    )
    monkeypatch.setattr(remote_onboarding, "confirm_host_key", lambda _p, info: False)

    done: dict[str, Any] = {}
    remote_onboarding.connect_with_onboarding(
        None,
        client,
        "srv",
        target="srv",
        on_success=lambda info: done.setdefault("ok", info),
        on_error=lambda msg, exc: done.setdefault("error", msg),
    )
    _run_until(qapp, done)

    assert done == {"error": "The remote host key was not trusted."}
    client.trust_host_key.assert_not_called()
    client.setup_key.assert_not_called()


def test_changed_host_key_has_no_override(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.connect_device.side_effect = _http_error("RemoteHostKeyChangedError", 502)
    shown: list[str] = []
    monkeypatch.setattr(
        remote_onboarding, "show_changed_host_key", lambda _p, msg: shown.append(msg)
    )

    done: dict[str, Any] = {}
    remote_onboarding.connect_with_onboarding(
        None,
        client,
        "srv",
        target="srv",
        on_success=lambda info: done.setdefault("ok", info),
        on_error=lambda msg, exc: done.setdefault("error", msg),
    )
    _run_until(qapp, done)

    assert shown == ["RemoteHostKeyChangedError happened"]
    assert "error" in done
    client.trust_host_key.assert_not_called()
    assert client.connect_device.call_count == 1


# --- Administrator access (sudo elevation) ---


def _elevation_flow(qapp: Any, client: MagicMock) -> dict[str, Any]:
    done: dict[str, Any] = {}
    elevated: list[bool] = []
    handled = remote_onboarding.handle_elevation_error(
        None,
        client,
        "srv",
        _http_error("RemoteElevationRequiredError", 403),
        target="alice@srv",
        retry=lambda: done.setdefault("retried", True),
        on_give_up=lambda reason: done.setdefault("gave_up", reason),
        on_elevated=lambda: elevated.append(True),
    )
    assert handled is True
    _run_until(qapp, done)
    done["elevated"] = bool(elevated)
    return done


def test_passwordless_sudo_elevates_without_prompt(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.elevate_device.return_value = True
    monkeypatch.setattr(
        remote_onboarding, "ask_sudo_password", lambda *_: pytest.fail("must not prompt")
    )

    done = _elevation_flow(qapp, client)

    assert done == {"retried": True, "elevated": True}
    client.elevate_device.assert_called_once_with("srv", None)


def test_sudo_password_is_asked_and_retried_after_a_wrong_one(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.elevate_device.side_effect = [
        _http_error("RemoteSudoAuthError", 401, password_required=True),
        _http_error("RemoteSudoAuthError", 401, password_required=False),
        True,
    ]
    prompts: list[str | None] = []
    passwords = iter(["wrong", "right"])

    def fake_ask(_parent: Any, target: str, retry_message: str | None) -> str:
        prompts.append(retry_message)
        return next(passwords)

    monkeypatch.setattr(remote_onboarding, "ask_sudo_password", fake_ask)

    done = _elevation_flow(qapp, client)

    assert done == {"retried": True, "elevated": True}
    assert [c.args for c in client.elevate_device.call_args_list] == [
        ("srv", None),
        ("srv", "wrong"),
        ("srv", "right"),
    ]
    assert prompts == [None, "The password was not accepted."]


def test_sudo_unavailable_explains_and_stops(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    client.elevate_device.side_effect = _http_error("RemoteSudoUnavailableError", 403)
    shown: list[str] = []
    monkeypatch.setattr(remote_onboarding, "show_sudo_unavailable", lambda _p, m: shown.append(m))

    done = _elevation_flow(qapp, client)

    assert shown == ["RemoteSudoUnavailableError happened"]
    assert "retried" not in done and done["elevated"] is False


def test_other_errors_are_not_elevation_requests(client: MagicMock) -> None:
    assert not remote_onboarding.handle_elevation_error(
        None,
        client,
        "srv",
        _http_error("ServiceNotFoundError", 404),
        target="srv",
        retry=lambda: None,
        on_give_up=lambda _r: None,
    )
    client.elevate_device.assert_not_called()


def test_create_system_service_on_remote_gets_admin_access_then_retries(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from servicedeck.api_client.models.service import CreatedService
    from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog

    created = CreatedService(
        success=True, service="myapp.service", path="/etc/systemd/system/myapp.service"
    )
    client.create_service.side_effect = [
        _http_error("RemoteElevationRequiredError", 403),
        created,
    ]
    client.elevate_device.side_effect = [
        _http_error("RemoteSudoAuthError", 401, password_required=True),
        True,
    ]
    monkeypatch.setattr(remote_onboarding, "ask_sudo_password", lambda *_: "sudo-pass")
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda *a: shown.append("created"))
    monkeypatch.setattr(QMessageBox, "critical", lambda *a: shown.append("failed"))

    elevated: list[bool] = []
    dlg = CreateServiceDialog(
        client=client,
        default_scope="system",
        device_id="srv",
        target="alice@srv",
        on_elevated=lambda: elevated.append(True),
    )
    dlg._name_edit.setText("myapp")
    dlg._exec_edit.setText("/usr/bin/myapp")
    dlg._on_create()

    for _ in range(50):
        if shown:
            break
        QThreadPool.globalInstance().waitForDone(1000)
        qapp.processEvents()

    assert shown == ["created"]
    assert elevated == [True]
    assert client.create_service.call_count == 2
    assert all(c.kwargs["scope"] == "system" for c in client.create_service.call_args_list)
    assert [c.args for c in client.elevate_device.call_args_list] == [
        ("srv", None),
        ("srv", "sudo-pass"),
    ]


def test_create_service_gives_up_cleanly_when_admin_access_is_cancelled(
    qapp: Any, client: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    from PySide6.QtWidgets import QMessageBox

    from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog

    client.create_service.side_effect = _http_error("RemoteElevationRequiredError", 403)
    client.elevate_device.side_effect = _http_error(
        "RemoteSudoAuthError", 401, password_required=True
    )
    monkeypatch.setattr(remote_onboarding, "ask_sudo_password", lambda *_: None)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "critical", lambda _p, _t, msg: shown.append(msg))

    dlg = CreateServiceDialog(client=client, default_scope="system", device_id="srv")
    dlg._name_edit.setText("myapp")
    dlg._on_create()

    for _ in range(50):
        if shown:
            break
        QThreadPool.globalInstance().waitForDone(1000)
        qapp.processEvents()

    assert len(shown) == 1 and "Administrator access was cancelled." in shown[0]
    assert client.create_service.call_count == 1
    assert dlg._create_btn.isEnabled()
