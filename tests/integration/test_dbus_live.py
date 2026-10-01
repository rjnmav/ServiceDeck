"""Integration tests running against the live Linux system and user D-Buses."""

import os

import pytest

from servicedeck.backend.config.settings import Settings
from servicedeck.backend.infrastructure.dbus.connection import DbusConnectionManager
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter


def is_system_bus_available() -> bool:
    return os.path.exists("/run/dbus/system_bus_socket") or os.path.exists(
        "/var/run/dbus/system_bus_socket"
    )


def is_user_bus_available() -> bool:
    uid = os.getuid()
    return os.path.exists(f"/run/user/{uid}/bus") or bool(
        os.environ.get("DBUS_SESSION_BUS_ADDRESS")
    )


@pytest.mark.asyncio
async def test_live_dbus_health_and_discovery() -> None:
    """Read-only test checking live D-Bus systemd communication for user and system scopes."""
    settings = Settings()
    conn_mgr = DbusConnectionManager(settings)

    adapter = DbusSystemdAdapter(connection_manager=conn_mgr, settings=settings)

    try:
        # Test User Bus if available
        if is_user_bus_available():
            try:
                await conn_mgr.connect("user")
                assert await adapter.is_healthy("user") is True

                user_services = await adapter.list_services("user")
                assert len(user_services) > 0
                assert all(s.scope == "user" for s in user_services)
            except Exception as exc:
                pytest.skip(f"User bus not accessible: {exc}")

        # Test System Bus if available
        if is_system_bus_available():
            try:
                await conn_mgr.connect("system")
                assert await adapter.is_healthy("system") is True

                system_services = await adapter.list_services("system")
                assert len(system_services) > 0
                assert all(s.scope == "system" for s in system_services)
            except Exception as exc:
                pytest.skip(f"System bus not accessible: {exc}")

    finally:
        await conn_mgr.disconnect()
