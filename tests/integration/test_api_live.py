"""Integration tests for the complete FastAPI application over live D-Bus."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings


def is_live_bus_available() -> bool:
    uid = os.getuid()
    return (
        os.path.exists(f"/run/user/{uid}/bus")
        or os.path.exists("/run/dbus/system_bus_socket")
        or bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS"))
    )


@pytest.mark.asyncio
async def test_live_fastapi_systemd_integration() -> None:
    """Full-stack integration test with default user scope and toggle to system scope."""
    if not is_live_bus_available():
        pytest.skip("Neither system nor user D-Bus socket available.")

    settings = Settings()
    app = create_app(settings=settings)

    transport = ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        # 1. Health check
        res_health = await client.get("/api/health")
        assert res_health.status_code == 200
        health_data = res_health.json()
        assert health_data["status"] in ("ok", "degraded")

        # 2. Scope check: default is user
        res_scope = await client.get("/api/scope")
        assert res_scope.status_code == 200
        assert res_scope.json()["active_scope"] == "user"

        # 3. Services list defaults to user scope
        res_user_services = await client.get("/api/services")
        assert res_user_services.status_code == 200
        user_services = res_user_services.json()
        assert len(user_services) > 0
        assert all(s["scope"] == "user" for s in user_services)

        # 4. Toggle scope to system
        res_toggle = await client.post("/api/scope", json={"scope": "system"})
        assert res_toggle.status_code == 200
        assert res_toggle.json()["active_scope"] == "system"

        # 5. Services list now returns system services
        res_sys_services = await client.get("/api/services")
        assert res_sys_services.status_code == 200
        sys_services = res_sys_services.json()
        assert len(sys_services) > 0
        assert all(s["scope"] == "system" for s in sys_services)

        # 6. Toggle back to user
        await client.post("/api/scope", json={"scope": "user"})
        res_back = await client.get("/api/scope")
        assert res_back.json()["active_scope"] == "user"
