"""Unit tests for DbusSystemdAdapter error handling, translation, and scope routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast.constants import MessageType
from dbus_fast.message import Message

from servicedeck.backend.exceptions import (
    PermissionDeniedError,
    ServiceNotFoundError,
    ServiceOperationError,
)
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter


class DummyVariant:
    def __init__(self, value: object) -> None:
        self.value = value


@pytest.fixture
def mock_bus() -> AsyncMock:
    bus = AsyncMock()
    bus.connected = True
    return bus


@pytest.fixture
def mock_connection_manager(mock_bus: AsyncMock) -> MagicMock:
    cm = MagicMock()
    cm.get_bus = AsyncMock(return_value=mock_bus)
    return cm


@pytest.fixture
def adapter(mock_connection_manager: MagicMock) -> DbusSystemdAdapter:
    return DbusSystemdAdapter(connection_manager=mock_connection_manager)


async def test_adapter_health_success(adapter: DbusSystemdAdapter, mock_bus: AsyncMock) -> None:
    reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        signature="v",
        body=[DummyVariant("255.4")],
    )
    mock_bus.call.return_value = reply

    assert await adapter.is_healthy("user") is True
    assert await adapter.is_healthy("system") is True


async def test_adapter_health_failure(adapter: DbusSystemdAdapter, mock_bus: AsyncMock) -> None:
    mock_bus.call.side_effect = Exception("Bus unreachable")
    assert await adapter.is_healthy("user") is False


async def test_adapter_list_services_user_scope(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock, mock_connection_manager: MagicMock
) -> None:
    units_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        signature="a(ssssssouso)",
        body=[
            [
                (
                    "pipewire.service",
                    "PipeWire Service",
                    "loaded",
                    "active",
                    "running",
                    "",
                    "/unit/pipewire",
                    0,
                    "",
                    "/",
                ),
            ]
        ],
    )
    files_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=2,
        signature="a(ss)",
        body=[
            [
                ("/usr/lib/systemd/user/pipewire.service", "enabled"),
                ("/usr/lib/systemd/user/dunst.service", "disabled"),
            ]
        ],
    )

    mock_bus.call.side_effect = [units_reply, files_reply]

    services = await adapter.list_services(scope="user")
    mock_connection_manager.get_bus.assert_called_with("user")
    assert len(services) == 2
    assert all(s.scope == "user" for s in services)


async def test_adapter_get_service_success(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock, mock_connection_manager: MagicMock
) -> None:
    load_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        signature="o",
        body=["/org/freedesktop/systemd1/unit/pipewire_2eservice"],
    )
    props_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=2,
        signature="a{sv}",
        body=[
            {
                "Id": DummyVariant("pipewire.service"),
                "Description": DummyVariant("PipeWire Service"),
                "LoadState": DummyVariant("loaded"),
                "ActiveState": DummyVariant("active"),
                "SubState": DummyVariant("running"),
                "UnitFileState": DummyVariant("enabled"),
            }
        ],
    )
    mock_bus.call.side_effect = [load_reply, props_reply]

    svc = await adapter.get_service("pipewire", scope="user")
    mock_connection_manager.get_bus.assert_called_with("user")
    assert svc.name == "pipewire.service"
    assert svc.scope == "user"
    assert svc.active_state == "active"


async def test_adapter_get_service_not_found_load_state(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock
) -> None:
    load_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=1,
        signature="o",
        body=["/org/freedesktop/systemd1/unit/missing_2eservice"],
    )
    props_reply = Message(
        message_type=MessageType.METHOD_RETURN,
        reply_serial=2,
        signature="a{sv}",
        body=[
            {
                "Id": DummyVariant("missing.service"),
                "LoadState": DummyVariant("not-found"),
            }
        ],
    )
    mock_bus.call.side_effect = [load_reply, props_reply]

    with pytest.raises(ServiceNotFoundError):
        await adapter.get_service("missing.service", scope="user")


async def test_adapter_permission_denied_translation(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock
) -> None:
    err_reply = Message(
        message_type=MessageType.ERROR,
        reply_serial=1,
        error_name="org.freedesktop.DBus.Error.AccessDenied",
        body=["Access denied by policy"],
    )
    mock_bus.call.return_value = err_reply

    with pytest.raises(PermissionDeniedError) as exc_info:
        await adapter.start_service("ssh.service", scope="system")
    assert exc_info.value.action == "start"


async def test_adapter_interactive_auth_translation(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock
) -> None:
    err_reply = Message(
        message_type=MessageType.ERROR,
        reply_serial=1,
        error_name="org.freedesktop.DBus.Error.InteractiveAuthorizationRequired",
        body=["Interactive authorization required"],
    )
    mock_bus.call.return_value = err_reply

    with pytest.raises(PermissionDeniedError) as exc_info:
        await adapter.restart_service("ssh.service", scope="system")
    assert exc_info.value.action == "restart"


async def test_adapter_service_operation_error(
    adapter: DbusSystemdAdapter, mock_bus: AsyncMock
) -> None:
    err_reply = Message(
        message_type=MessageType.ERROR,
        reply_serial=1,
        error_name="org.freedesktop.systemd1.UnitCannotBeStarted",
        body=["Service has failed and is in bad state"],
    )
    mock_bus.call.return_value = err_reply

    with pytest.raises(ServiceOperationError) as exc_info:
        await adapter.start_service("broken.service", scope="system")
    assert exc_info.value.operation == "start"
