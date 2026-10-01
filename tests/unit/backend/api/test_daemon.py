"""Unit tests for /api/daemon endpoints."""

from httpx import AsyncClient
from tests.conftest import FakeSystemdAdapter


async def test_daemon_reload_default_scope(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    response = await client.post("/api/daemon/reload")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["scope"] == "user"
    assert ("reload_daemon", "*", "user") in fake_adapter.calls


async def test_daemon_reload_system_scope(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    response = await client.post("/api/daemon/reload?scope=system")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["scope"] == "system"
    assert ("reload_daemon", "*", "system") in fake_adapter.calls


async def test_daemon_reload_permission_denied(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.denied_operations.add(("reload_daemon", "system"))
    response = await client.post("/api/daemon/reload?scope=system")
    assert response.status_code == 403
    data = response.json()
    assert data["error"] == "PermissionDeniedError"
