"""Unit tests for the /api/health endpoint."""

from httpx import AsyncClient
from tests.conftest import FakeSystemdAdapter


async def test_root_endpoint(client: AsyncClient) -> None:
    response = await client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "running"
    assert "docs" in data
    assert "endpoints" in data


async def test_health_endpoint_healthy(client: AsyncClient) -> None:
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["systemd_connected"] is True
    assert data["systemd_user_connected"] is True
    assert data["systemd_system_connected"] is True
    assert data["active_scope"] == "user"
    assert "version" in data
    assert "listen_address" in data
    assert data["allow_interactive_authorization"] is True


async def test_health_endpoint_degraded(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.healthy_scopes["system"] = False
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["systemd_connected"] is True
    assert data["systemd_user_connected"] is True
    assert data["systemd_system_connected"] is False


async def test_health_endpoint_down(client: AsyncClient, fake_adapter: FakeSystemdAdapter) -> None:
    fake_adapter.healthy_scopes["user"] = False
    fake_adapter.healthy_scopes["system"] = False
    response = await client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "down"
    assert data["systemd_connected"] is False
