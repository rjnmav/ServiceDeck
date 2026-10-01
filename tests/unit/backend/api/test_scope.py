"""Unit tests for the /api/scope toggle API endpoints."""

from httpx import AsyncClient


async def test_get_active_scope_default(client: AsyncClient) -> None:
    response = await client.get("/api/scope")
    assert response.status_code == 200
    data = response.json()
    assert data["active_scope"] == "user"
    assert "user" in data["available_scopes"]
    assert "system" in data["available_scopes"]


async def test_toggle_active_scope(client: AsyncClient) -> None:
    # 1. Verify initially 'user'
    r1 = await client.get("/api/scope")
    assert r1.json()["active_scope"] == "user"

    # Services list returns user services
    r_user_svcs = await client.get("/api/services")
    assert any(s["name"] == "pipewire.service" for s in r_user_svcs.json())

    # 2. Toggle to 'system'
    r2 = await client.post("/api/scope", json={"scope": "system"})
    assert r2.status_code == 200
    assert r2.json()["active_scope"] == "system"

    # Services list now returns system services without passing ?scope=system!
    r_sys_svcs = await client.get("/api/services")
    assert any(s["name"] == "ssh.service" for s in r_sys_svcs.json())
    assert all(s["scope"] == "system" for s in r_sys_svcs.json())

    # 3. Toggle back to 'user'
    r3 = await client.post("/api/scope", json={"scope": "user"})
    assert r3.status_code == 200
    assert r3.json()["active_scope"] == "user"

    r_user_svcs_again = await client.get("/api/services")
    assert any(s["name"] == "pipewire.service" for s in r_user_svcs_again.json())
    assert all(s["scope"] == "user" for s in r_user_svcs_again.json())


async def test_toggle_active_scope_invalid(client: AsyncClient) -> None:
    response = await client.post("/api/scope", json={"scope": "invalid_scope"})
    assert response.status_code == 422
