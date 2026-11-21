"""Lightweight, stdlib-only D-Bus settings.

The remote agent is shipped to remote hosts as pure-Python source, so it cannot
depend on pydantic (whose core is a compiled extension). The D-Bus layer therefore
depends only on the small structural protocol defined here; the backend's pydantic
``Settings`` satisfies it unchanged.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Protocol

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


class DbusSettingsLike(Protocol):
    """Settings consumed by the D-Bus connection manager and systemd adapter."""

    @property
    def dbus_address(self) -> str | None: ...

    @property
    def allow_interactive_authorization(self) -> bool: ...


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    return default


@dataclass(frozen=True, slots=True)
class DbusSettings:
    """Plain dataclass implementation of :class:`DbusSettingsLike`."""

    dbus_address: str | None = None
    allow_interactive_authorization: bool = True

    @classmethod
    def from_env(cls) -> DbusSettings:
        """Build settings from the same ``SERVICEDECK_*`` variables the backend reads."""
        return cls(
            dbus_address=os.environ.get("SERVICEDECK_DBUS_ADDRESS") or None,
            allow_interactive_authorization=_env_bool(
                "SERVICEDECK_ALLOW_INTERACTIVE_AUTHORIZATION", True
            ),
        )


__all__ = ["DbusSettings", "DbusSettingsLike"]
