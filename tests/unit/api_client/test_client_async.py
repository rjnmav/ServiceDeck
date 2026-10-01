"""Tests for AsyncServiceDeckClient."""

import httpx
import pytest

from servicedeck.api_client import AsyncServiceDeckClient
from servicedeck.api_client.transport import AsyncTransport


def create_mock_async_client(handler) -> AsyncServiceDeckClient:
    mock_transport = httpx.MockTransport(handler)
    transport = AsyncTransport(base_url="http://testserver")
    transport._client = httpx.AsyncClient(transport=mock_transport, base_url="http://testserver")
    return AsyncServiceDeckClient(transport=transport)


@pytest.mark.asyncio
async def test_async_client_lifecycle_and_operations():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/health":
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "systemd_connected": True,
                    "active_scope": "user",
                    "version": "2.0.0",
                },
            )
        if path == "/api/scope" and request.method == "GET":
            return httpx.Response(
                200, json={"active_scope": "user", "available_scopes": ["user", "system"]}
            )
        if path == "/api/scope" and request.method == "POST":
            return httpx.Response(
                200, json={"active_scope": "system", "available_scopes": ["user", "system"]}
            )
        if path == "/api/services" and request.method == "GET":
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "test.service",
                        "description": "Test",
                        "load_state": "loaded",
                        "active_state": "active",
                        "sub_state": "running",
                        "unit_file_state": "enabled",
                    }
                ],
            )
        if path == "/api/services/test.service" and request.method == "GET":
            return httpx.Response(
                200,
                json={
                    "name": "test.service",
                    "description": "Test",
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "unit_file_state": "enabled",
                },
            )
        if path == "/api/services/test.service/mask":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "service": "test.service",
                    "operation": "mask",
                    "scope": "user",
                },
            )
        if path == "/api/services/test.service/unmask":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "service": "test.service",
                    "operation": "unmask",
                    "scope": "user",
                },
            )
        if path == "/api/daemon/reload":
            return httpx.Response(
                200, json={"success": True, "scope": "user", "message": "reloaded"}
            )
        if path == "/api/services/test.service/unit-file":
            return httpx.Response(
                200,
                json={
                    "service": "test.service",
                    "fragment_path": "/path/to/unit",
                    "content": "[Unit]",
                    "scope": "user",
                },
            )
        if path == "/api/services/test.service/resources":
            return httpx.Response(
                200,
                json={
                    "service": "test.service",
                    "cpu_usage_nsec": 100,
                    "active_state": "active",
                    "scope": "user",
                },
            )
        if path == "/api/services/test.service/logs":
            return httpx.Response(
                200,
                json={"service": "test.service", "logs": "logs...", "scope": "user", "lines": 200},
            )
        if path == "/api/services/create":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "service": "new.service",
                    "path": "/path/to/new",
                    "scope": "user",
                },
            )
        return httpx.Response(404)

    client = create_mock_async_client(handler)
    async with client:
        health = await client.health()
        assert health.status == "ok"

        scope = await client.get_scope()
        assert scope.active_scope == "user"

        scope2 = await client.set_scope("system")
        assert scope2.active_scope == "system"

        svcs = await client.list_services()
        assert len(svcs) == 1

        svc = await client.get_service("test.service")
        assert svc.name == "test.service"

        mask_res = await client.mask_service("test.service")
        assert mask_res.success is True

        unmask_res = await client.unmask_service("test.service")
        assert unmask_res.success is True

        reload_res = await client.reload_daemon()
        assert reload_res.success is True

        unit = await client.get_unit_file("test.service")
        assert unit.content == "[Unit]"

        res = await client.get_resources("test.service")
        assert res.cpu_usage_nsec == 100

        logs = await client.get_logs("test.service")
        assert logs.logs == "logs..."

        created = await client.create_service("new.service", "[Unit]\n")
        assert created.success is True
