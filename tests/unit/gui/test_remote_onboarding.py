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
