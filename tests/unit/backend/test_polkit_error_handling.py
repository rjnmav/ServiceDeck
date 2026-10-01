"""Unit tests for Polkit-aware D-Bus error translation and message flags."""

import pytest
from dbus_fast.constants import MessageFlag, MessageType
from dbus_fast.message import Message

from servicedeck.backend.config.settings import Settings
from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    PermissionDeniedError,
    PolkitAgentUnavailableError,
)
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter


def test_interactive_authorization_required_translates_to_polkit_agent_unavailable() -> None:
    """InteractiveAuthorizationRequired D-Bus error raises PolkitAgentUnavailableError."""
    adapter = DbusSystemdAdapter(settings=Settings())
    reply = Message(
        message_type=MessageType.ERROR,
        reply_serial=1,
        error_name="org.freedesktop.DBus.Error.InteractiveAuthorizationRequired",
        body=["Interactive authentication required."],
    )

    with pytest.raises(PolkitAgentUnavailableError) as exc_info:
        adapter._handle_error_reply(reply, "restart", "nginx.service", "system")

    err = exc_info.value
    assert isinstance(err, PermissionDeniedError)
    assert err.action == "restart"
    assert err.service_name == "nginx.service"
    assert err.scope == "system"
    assert "No Polkit authentication agent is available" in err.message


def test_access_denied_translates_to_authorization_denied() -> None:
    """AccessDenied D-Bus error raises AuthorizationDeniedError."""
    adapter = DbusSystemdAdapter(settings=Settings())
    reply = Message(
        message_type=MessageType.ERROR,
        reply_serial=1,
        error_name="org.freedesktop.DBus.Error.AccessDenied",
        body=["Permission denied by system policy."],
    )

    with pytest.raises(AuthorizationDeniedError) as exc_info:
        adapter._handle_error_reply(reply, "stop", "sshd.service", "system")

    err = exc_info.value
    assert isinstance(err, PermissionDeniedError)
    assert err.action == "stop"
    assert err.service_name == "sshd.service"
    assert "Permission denied" in str(err)


def test_message_flags_reflects_setting() -> None:
    """_get_message_flags enables ALLOW_INTERACTIVE_AUTHORIZATION when setting is True."""
    settings_interactive = Settings(allow_interactive_authorization=True)
    adapter_interactive = DbusSystemdAdapter(settings=settings_interactive)
    assert (
        adapter_interactive._get_message_flags("system")
        == MessageFlag.ALLOW_INTERACTIVE_AUTHORIZATION
    )
    assert (
        adapter_interactive._get_message_flags("user")
        == MessageFlag.ALLOW_INTERACTIVE_AUTHORIZATION
    )

    settings_non_interactive = Settings(allow_interactive_authorization=False)
    adapter_non_interactive = DbusSystemdAdapter(settings=settings_non_interactive)
    assert adapter_non_interactive._get_message_flags("system") == MessageFlag.NONE
    assert adapter_non_interactive._get_message_flags("user") == MessageFlag.NONE
