"""DbusSystemdAdapter reads restart count, last exit and failure time with the resources."""

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from dbus_fast.constants import MessageType
from dbus_fast.message import Message
from dbus_fast.signature import Variant

from servicedeck.backend.infrastructure.dbus.config import DbusSettings
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter

UNSET = 18446744073709551615


def ok(*body: Any) -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=list(body), error_name=None)


class HealthBus:
    def __init__(self, unit: dict[str, Variant], service: dict[str, Variant]) -> None:
        self.unit = unit
        self.service = service

    async def call(self, msg: Message) -> SimpleNamespace:
        if msg.member == "LoadUnit":
            return ok("/org/freedesktop/systemd1/unit/web_2eservice")
        if msg.member == "GetAll":
            return ok(self.unit if msg.body[0].endswith(".Unit") else self.service)
        if msg.member == "GetProcesses":
            return ok([])
        raise AssertionError(msg.member)


def _adapter(bus: HealthBus) -> DbusSystemdAdapter:
    cm = MagicMock()
    cm.get_bus = AsyncMock(return_value=bus)
    return DbusSystemdAdapter(connection_manager=cm, settings=DbusSettings())


async def test_failed_service_health() -> None:
    bus = HealthBus(
        unit={
            "ActiveState": Variant("s", "failed"),
            "ActiveEnterTimestamp": Variant("t", 0),
            "StateChangeTimestamp": Variant("t", 1_700_000_000_000_000),
        },
        service={
            "NRestarts": Variant("u", 5),
            "Result": Variant("s", "exit-code"),
            "ExecMainCode": Variant("i", 1),
            "ExecMainStatus": Variant("i", 203),
            "ExecMainExitTimestamp": Variant("t", 1_699_999_999_000_000),
            "MainPID": Variant("u", 0),
            "MemoryCurrent": Variant("t", UNSET),
        },
    )
    usage = await _adapter(bus).get_service_resources("web", scope="system")

    assert usage.active_state == "failed"
    assert usage.is_active is False
    assert usage.n_restarts == 5
    assert usage.result == "exit-code"
    assert (usage.exec_main_code, usage.exec_main_status) == (1, 203)
    assert usage.exec_main_exit_timestamp_usec == 1_699_999_999_000_000
    assert usage.state_change_timestamp_usec == 1_700_000_000_000_000
    assert usage.active_enter_timestamp_usec is None
    assert usage.memory_current is None
    assert usage.main_pid is None


async def test_older_systemd_without_health_properties() -> None:
    bus = HealthBus(unit={"ActiveState": Variant("s", "active")}, service={})
    usage = await _adapter(bus).get_service_resources("web")
    assert usage.active_state == "active"
    assert usage.n_restarts is None
    assert usage.result is None
    assert usage.exec_main_code is None
    assert usage.state_change_timestamp_usec is None
