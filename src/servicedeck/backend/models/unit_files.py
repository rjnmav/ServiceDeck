"""Unit file and drop-in override models (stdlib only: shipped inside the remote agent)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Name of the drop-in written by "Edit override", the same one ``systemctl edit`` uses.
DEFAULT_DROP_IN = "override.conf"

_DROP_IN_NAME = re.compile(r"^[A-Za-z0-9_.@-]+\.conf$")

#: Directory for administrator-owned system units (never the vendor ``/usr/lib`` tree).
SYSTEM_UNIT_DIR = Path("/etc/systemd/system")


def writable_unit_dir(scope: str) -> Path:
    """Return the directory where ServiceDeck writes units and drop-ins for ``scope``."""
    if scope == "system":
        return SYSTEM_UNIT_DIR
    return Path.home() / ".config" / "systemd" / "user"


def drop_in_dir(unit_name: str, scope: str) -> Path:
    """Return the writable ``<unit>.d`` directory for ``unit_name`` in ``scope``."""
    return writable_unit_dir(scope) / f"{unit_name}.d"


def is_valid_drop_in_name(name: str) -> bool:
    """True if ``name`` is a plain ``*.conf`` file name (no directories, no traversal)."""
    return bool(_DROP_IN_NAME.match(name)) and name not in (".conf", "..conf")


@dataclass(frozen=True, slots=True)
class DropIn:
    """One drop-in file that systemd applies on top of the unit's main file."""

    path: str
    content: str
    #: True when the file lives in ServiceDeck's writable directory for the scope.
    editable: bool = False


@dataclass(frozen=True, slots=True)
class UnitFileInfo:
    """A unit's main file, its drop-ins, and where an override would be written."""

    service: str
    scope: str
    fragment_path: str | None
    content: str
    drop_ins: list[DropIn] = field(default_factory=list)
    override_path: str | None = None
    need_daemon_reload: bool = False

    @property
    def editable_drop_ins(self) -> list[DropIn]:
        return [drop_in for drop_in in self.drop_ins if drop_in.editable]


@dataclass(frozen=True, slots=True)
class OverrideResult:
    """Outcome of writing (or, for empty content, removing) a drop-in override."""

    service: str
    scope: str
    path: str
    removed: bool = False
    load_state: str = "unknown"
    warnings: list[str] = field(default_factory=list)


def unit_info_from_dict(data: dict[str, Any]) -> UnitFileInfo:
    """Rebuild a :class:`UnitFileInfo` sent over the agent protocol."""
    return UnitFileInfo(
        service=str(data.get("service", "")),
        scope=str(data.get("scope", "user")),
        fragment_path=data.get("fragment_path"),
        content=str(data.get("content", "")),
        drop_ins=[
            DropIn(
                path=str(item.get("path", "")),
                content=str(item.get("content", "")),
                editable=bool(item.get("editable", False)),
            )
            for item in data.get("drop_ins") or []
        ],
        override_path=data.get("override_path"),
        need_daemon_reload=bool(data.get("need_daemon_reload", False)),
    )


def override_result_from_dict(data: dict[str, Any]) -> OverrideResult:
    """Rebuild an :class:`OverrideResult` sent over the agent protocol."""
    return OverrideResult(
        service=str(data.get("service", "")),
        scope=str(data.get("scope", "user")),
        path=str(data.get("path", "")),
        removed=bool(data.get("removed", False)),
        load_state=str(data.get("load_state", "unknown")),
        warnings=[str(w) for w in data.get("warnings") or []],
    )


__all__ = [
    "DEFAULT_DROP_IN",
    "SYSTEM_UNIT_DIR",
    "DropIn",
    "OverrideResult",
    "UnitFileInfo",
    "drop_in_dir",
    "is_valid_drop_in_name",
    "override_result_from_dict",
    "unit_info_from_dict",
    "writable_unit_dir",
]
