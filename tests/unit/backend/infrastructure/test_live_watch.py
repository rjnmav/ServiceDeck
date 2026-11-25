"""Unit tests for the D-Bus live service watcher and journal follower."""

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast.constants import MessageType
from dbus_fast.message import Message
from dbus_fast.signature import Variant

from servicedeck.backend.exceptions import SystemdConnectionError
from servicedeck.backend.infrastructure.dbus.config import DbusSettings
from servicedeck.backend.infrastructure.dbus.systemd import (
    DbusSystemdAdapter,
    unit_name_from_path,
)

UNIT_PATH = "/org/freedesktop/systemd1/unit/nginx_2eservice"


def ok(*body: Any) -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=list(body), error_name=None)


def err(name: str) -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.ERROR, body=["nope"], error_name=name)


class FakeBus:
    """Enough of a dbus-fast MessageBus to drive the watcher."""

    def __init__(self) -> None:
        self.connected = True
        self.handlers: list[Any] = []
        self.calls: list[tuple[str, list[Any]]] = []
        self.loaded: dict[str, dict[str, Any]] = {}
        self.unit_files: dict[str, str] = {}

    def add_message_handler(self, handler: Any) -> None:
        self.handlers.append(handler)

    def remove_message_handler(self, handler: Any) -> None:
        self.handlers.remove(handler)

    def emit(self, path: str, interface: str, member: str, signature: str, body: list[Any]) -> None:
        msg = Message.new_signal(path, interface, member, signature, body)
        for handler in list(self.handlers):
            handler(msg)

    async def call(self, msg: Message) -> SimpleNamespace:
        self.calls.append((msg.member, list(msg.body)))
        if msg.member in ("AddMatch", "RemoveMatch", "Subscribe", "Unsubscribe"):
            return ok()
        if msg.member == "GetUnit":
            name = msg.body[0]
            if name not in self.loaded:
                return err("NoSuchUnit")
            return ok("/org/freedesktop/systemd1/unit/" + name.replace(".", "_2e"))
        if msg.member == "GetAll":
            name = unit_name_from_path(msg.path)
            return ok({k: Variant("s", v) for k, v in self.loaded[name].items()})
        if msg.member == "GetUnitFileState":
            name = msg.body[0]
            return ok(self.unit_files[name]) if name in self.unit_files else err("FileNotFound")
        raise AssertionError(f"unexpected call {msg.member}")

    def members(self) -> list[str]:
        return [member for member, _ in self.calls]


@pytest.fixture
def bus() -> FakeBus:
    return FakeBus()


@pytest.fixture
def adapter(bus: FakeBus) -> DbusSystemdAdapter:
    cm = MagicMock()
    cm.get_bus = AsyncMock(return_value=bus)
    adapter = DbusSystemdAdapter(connection_manager=cm, settings=DbusSettings())
    adapter.WATCH_DEBOUNCE_SECONDS = 0.0
    adapter.WATCH_LIVENESS_SECONDS = 0.05
    return adapter


def test_unit_name_from_path() -> None:
    assert unit_name_from_path(UNIT_PATH) == "nginx.service"
    assert unit_name_from_path("/org/freedesktop/systemd1/unit/getty_40tty1_2eservice") == (
        "getty@tty1.service"
    )
    assert unit_name_from_path("/org/freedesktop/systemd1") is None


async def test_watch_reports_property_changes(bus: FakeBus, adapter: DbusSystemdAdapter) -> None:
    watch = adapter.watch_services("system")
    ready = await anext(watch)
    assert ready.kind == "ready"
    assert ready.scope == "system"
    assert bus.members().count("AddMatch") == 2
    assert "Subscribe" in bus.members()

    bus.loaded["nginx.service"] = {
        "Description": "Web",
        "LoadState": "loaded",
        "ActiveState": "failed",
        "SubState": "failed",
        "UnitFileState": "enabled",
    }
    bus.emit(
        UNIT_PATH,
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        "sa{sv}as",
        ["org.freedesktop.systemd1.Unit", {}, []],
    )
    event = await asyncio.wait_for(anext(watch), 1)
    assert event.kind == "changed"
    assert event.service is not None
    assert event.service.name == "nginx.service"
    assert event.service.active_state == "failed"
    assert event.service.scope == "system"
    # Never LoadUnit: that would resurrect units systemd just garbage-collected.
    assert "LoadUnit" not in bus.members()
    await watch.aclose()


async def test_watch_ignores_non_service_units_and_other_interfaces(
    bus: FakeBus, adapter: DbusSystemdAdapter
) -> None:
    watch = adapter.watch_services()
    await anext(watch)
    bus.emit(
        "/org/freedesktop/systemd1/unit/tmp_2emount",
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        "sa{sv}as",
        ["org.freedesktop.systemd1.Unit", {}, []],
    )
    bus.emit(
        UNIT_PATH,
        "org.freedesktop.DBus.Properties",
        "PropertiesChanged",
        "sa{sv}as",
        ["org.freedesktop.systemd1.Service", {}, []],
    )
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(anext(watch), 0.2)
    await watch.aclose()


async def test_watch_unloaded_unit_with_file_is_inactive_and_missing_one_is_removed(
    bus: FakeBus, adapter: DbusSystemdAdapter
) -> None:
    watch = adapter.watch_services()
    await anext(watch)
    bus.unit_files["kept.service"] = "disabled"
    manager = "org.freedesktop.systemd1.Manager"
    bus.emit("/org/freedesktop/systemd1", manager, "UnitRemoved", "so", ["kept.service", "/x"])
    bus.emit("/org/freedesktop/systemd1", manager, "UnitRemoved", "so", ["gone.service", "/y"])

    first = await asyncio.wait_for(anext(watch), 1)
    second = await asyncio.wait_for(anext(watch), 1)
    events = {e.name: e for e in (first, second)}
    assert events["gone.service"].kind == "removed"
    kept = events["kept.service"]
    assert kept.kind == "changed"
    assert kept.service is not None
    assert (kept.service.active_state, kept.service.unit_file_state) == ("inactive", "disabled")
    await watch.aclose()


async def test_watch_resyncs_after_daemon_reload(bus: FakeBus, adapter: DbusSystemdAdapter) -> None:
    watch = adapter.watch_services()
    await anext(watch)
    manager = "org.freedesktop.systemd1.Manager"
    bus.emit("/org/freedesktop/systemd1", manager, "Reloading", "b", [True])
    bus.emit("/org/freedesktop/systemd1", manager, "Reloading", "b", [False])
    event = await asyncio.wait_for(anext(watch), 1)
    assert event.kind == "resync"
    await watch.aclose()


async def test_watch_cleans_up_and_refcounts_subscription(
    bus: FakeBus, adapter: DbusSystemdAdapter
) -> None:
    first = adapter.watch_services()
    second = adapter.watch_services()
    await anext(first)
    await anext(second)
    assert bus.members().count("Subscribe") == 1

    await first.aclose()
    assert "Unsubscribe" not in bus.members()
    await second.aclose()
    assert bus.members().count("Unsubscribe") == 1
    assert bus.members().count("RemoveMatch") == 4
    assert bus.handlers == []


async def test_watch_ends_when_bus_disconnects(bus: FakeBus, adapter: DbusSystemdAdapter) -> None:
    watch = adapter.watch_services()
    await anext(watch)
    bus.connected = False
    with pytest.raises(SystemdConnectionError, match="Lost"):
        await asyncio.wait_for(anext(watch), 1)


async def test_follow_logs_streams_journalctl_and_terminates_it(
    adapter: DbusSystemdAdapter, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[list[str]] = []
    real_exec = asyncio.create_subprocess_exec

    async def fake_exec(*cmd: str, **kwargs: Any) -> Any:
        started.append(list(cmd))
        script = "print('line one', flush=True); print('line two', flush=True); import time; time.sleep(30)"
        return await real_exec("python3", "-c", script, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

    logs = adapter.follow_service_logs("nginx", lines=5, scope="system")
    assert await anext(logs) == ""
    assert await asyncio.wait_for(anext(logs), 5) == "line one"
    assert await asyncio.wait_for(anext(logs), 5) == "line two"
    await logs.aclose()

    assert started == [["journalctl", "-u", "nginx.service", "-n", "5", "--no-pager", "--follow"]]
