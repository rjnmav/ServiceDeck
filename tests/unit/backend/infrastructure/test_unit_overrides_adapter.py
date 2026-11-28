"""DbusSystemdAdapter drop-in reading, writing, rollback and revert against a fake bus."""

import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from dbus_fast.constants import MessageType
from dbus_fast.message import Message
from dbus_fast.signature import Variant

from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    ServiceNotFoundError,
    ServiceOperationError,
)
from servicedeck.backend.infrastructure.dbus.config import DbusSettings
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter
from servicedeck.backend.models import unit_files

UNIT = "demo.service"


def ok(*body: Any) -> SimpleNamespace:
    return SimpleNamespace(message_type=MessageType.METHOD_RETURN, body=list(body), error_name=None)


class UnitBus:
    """Fake systemd: one unit whose LoadState depends on its drop-ins after each reload."""

    def __init__(self, unit_dir: Path) -> None:
        self.unit_dir = unit_dir
        self.fragment = unit_dir / UNIT
        self.vendor_drop_in: Path | None = None
        self.load_state = "loaded"
        self.reloads = 0
        self.need_reload = False

    def _drop_ins(self) -> list[str]:
        paths = sorted((self.unit_dir / f"{UNIT}.d").glob("*.conf"))
        if self.vendor_drop_in is not None:
            paths.insert(0, self.vendor_drop_in)
        return [str(p) for p in paths]

    async def call(self, msg: Message) -> SimpleNamespace:
        if msg.member == "LoadUnit":
            return ok("/org/freedesktop/systemd1/unit/demo_2eservice")
        if msg.member == "Reload":
            self.reloads += 1
            bad = any("Type=bogus" in Path(p).read_text() for p in self._drop_ins())
            self.load_state = "bad-setting" if bad else "loaded"
            return ok()
        if msg.member == "GetAll":
            props = {
                "LoadState": Variant("s", self.load_state),
                "FragmentPath": Variant("s", str(self.fragment)),
                "DropInPaths": Variant("as", self._drop_ins()),
                "NeedDaemonReload": Variant("b", self.need_reload),
                "LoadError": Variant(
                    "(ss)",
                    ["org.freedesktop.systemd1.BadSetting", "Unit has a bad setting"]
                    if self.load_state == "bad-setting"
                    else ["", ""],
                ),
            }
            return ok(props)
        raise AssertionError(f"unexpected call {msg.member}")


@pytest.fixture
def system_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    directory = tmp_path / "etc-systemd-system"
    directory.mkdir()
    monkeypatch.setattr(unit_files, "SYSTEM_UNIT_DIR", directory)
    return directory


@pytest.fixture
def bus(system_dir: Path) -> UnitBus:
    bus = UnitBus(system_dir)
    bus.fragment.write_text("[Unit]\nDescription=Demo\n[Service]\nExecStart=/bin/true\n")
    return bus


@pytest.fixture
def adapter(bus: UnitBus) -> DbusSystemdAdapter:
    cm = MagicMock()
    cm.get_bus = AsyncMock(return_value=bus)
    return DbusSystemdAdapter(connection_manager=cm, settings=DbusSettings())


async def test_unit_info_reads_fragment_and_drop_ins(
    adapter: DbusSystemdAdapter, bus: UnitBus, tmp_path: Path
) -> None:
    vendor = tmp_path / "usr-lib" / f"{UNIT}.d" / "10-vendor.conf"
    vendor.parent.mkdir(parents=True)
    vendor.write_text("[Service]\nNice=1\n")
    bus.vendor_drop_in = vendor
    override = bus.unit_dir / f"{UNIT}.d" / "override.conf"
    override.parent.mkdir()
    override.write_text("[Service]\nNice=5\n")
    bus.need_reload = True

    info = await adapter.get_unit_info(UNIT, scope="system")

    assert info.fragment_path == str(bus.fragment)
    assert "Description=Demo" in info.content
    assert [(d.path, d.editable) for d in info.drop_ins] == [
        (str(vendor), False),
        (str(override), True),
    ]
    assert info.override_path == str(override)
    assert info.need_daemon_reload is True
    # The old tuple API still works.
    assert await adapter.get_unit_file(UNIT, scope="system") == (str(bus.fragment), info.content)


async def test_write_override_creates_drop_in_and_reloads(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    result = await adapter.write_override(UNIT, "[Service]\nNice=5", scope="system")

    target = bus.unit_dir / f"{UNIT}.d" / "override.conf"
    assert result.path == str(target)
    assert result.load_state == "loaded"
    assert target.read_text() == "[Service]\nNice=5\n"
    assert oct(target.stat().st_mode & 0o777) == "0o644"
    assert bus.reloads == 1
    assert not list(target.parent.glob(".*tmp"))


async def test_bad_setting_restores_previous_override(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system")

    with pytest.raises(ServiceOperationError, match="Unit has a bad setting"):
        await adapter.write_override(UNIT, "[Service]\nType=bogus\n", scope="system")

    target = bus.unit_dir / f"{UNIT}.d" / "override.conf"
    assert target.read_text() == "[Service]\nNice=5\n"
    assert bus.load_state == "loaded"
    assert bus.reloads == 3  # write, rejected write, restore


async def test_bad_setting_on_new_override_removes_it(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    with pytest.raises(ServiceOperationError, match="previous configuration was restored"):
        await adapter.write_override(UNIT, "[Service]\nType=bogus\n", scope="system")

    assert not (bus.unit_dir / f"{UNIT}.d").exists()
    assert bus.load_state == "loaded"


async def test_syntax_errors_never_touch_disk(adapter: DbusSystemdAdapter, bus: UnitBus) -> None:
    with pytest.raises(ServiceOperationError, match="inside a section"):
        await adapter.write_override(UNIT, "Nice=5\n", scope="system")
    assert not (bus.unit_dir / f"{UNIT}.d").exists()
    assert bus.reloads == 0


@pytest.mark.parametrize("name", ["../evil.conf", "a/b.conf", "override", ".conf"])
async def test_invalid_drop_in_names_are_rejected(adapter: DbusSystemdAdapter, name: str) -> None:
    with pytest.raises(ServiceOperationError, match="Invalid drop-in name"):
        await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system", drop_in=name)


async def test_not_found_unit_is_rejected(adapter: DbusSystemdAdapter, bus: UnitBus) -> None:
    bus.load_state = "not-found"
    with pytest.raises(ServiceNotFoundError):
        await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system")


async def test_comment_only_content_removes_override(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system")

    result = await adapter.write_override(UNIT, "# cleared\n\n", scope="system")

    assert result.removed is True
    assert not (bus.unit_dir / f"{UNIT}.d").exists()


async def test_revert_removes_only_writable_drop_ins(
    adapter: DbusSystemdAdapter, bus: UnitBus, tmp_path: Path
) -> None:
    vendor = tmp_path / "vendor.conf"
    vendor.write_text("[Service]\nNice=1\n")
    bus.vendor_drop_in = vendor
    await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system")
    await adapter.write_override(
        UNIT, "[Service]\nMemoryMax=1G\n", scope="system", drop_in="m.conf"
    )
    keep = bus.unit_dir / f"{UNIT}.d" / "notes.txt"
    keep.write_text("not a drop-in")

    removed = await adapter.revert_overrides(UNIT, scope="system")

    assert [Path(p).name for p in removed] == ["m.conf", "override.conf"]
    assert vendor.exists()
    assert keep.exists()  # directory kept because it is not empty


async def test_revert_without_drop_ins_does_not_reload(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    assert await adapter.revert_overrides(UNIT, scope="system") == []
    assert bus.reloads == 0


async def test_unwritable_directory_raises_authorization_denied(
    adapter: DbusSystemdAdapter, bus: UnitBus
) -> None:
    if os.geteuid() == 0:
        pytest.skip("running as root: permissions are not enforced")
    bus.unit_dir.chmod(0o555)
    try:
        with pytest.raises(AuthorizationDeniedError, match="administrator access"):
            await adapter.write_override(UNIT, "[Service]\nNice=5\n", scope="system")
    finally:
        bus.unit_dir.chmod(0o755)


async def test_create_service_rejects_bad_syntax(adapter: DbusSystemdAdapter) -> None:
    with pytest.raises(ServiceOperationError, match="Line 3"):
        await adapter.create_service(
            "new.service", "[Unit]\n[Service]\nthis is not valid\n", scope="system"
        )


async def test_create_service_writes_atomically(adapter: DbusSystemdAdapter, bus: UnitBus) -> None:
    path = await adapter.create_service(
        "new.service", "[Unit]\nDescription=x\n[Service]\nExecStart=/bin/true\n", scope="system"
    )
    assert Path(path) == bus.unit_dir / "new.service"
    assert "ExecStart=/bin/true" in Path(path).read_text()
    assert bus.reloads == 1
