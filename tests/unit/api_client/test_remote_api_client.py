"""Tests for remote operations in ServiceDeckClient and AsyncServiceDeckClient."""

import httpx

from servicedeck.api_client import AsyncServiceDeckClient, ServiceDeckClient
from servicedeck.api_client.models.remote import RemoteConnectionInfo, RemoteDevice
from servicedeck.api_client.transport import AsyncTransport, SyncTransport


def create_mock_sync_client(handler) -> ServiceDeckClient:
    mock_transport = httpx.MockTransport(handler)
    transport = SyncTransport(base_url="http://testserver")
    transport._client = httpx.Client(transport=mock_transport, base_url="http://testserver")
    return ServiceDeckClient(transport=transport)


def create_mock_async_client(handler) -> AsyncServiceDeckClient:
    mock_transport = httpx.MockTransport(handler)
    transport = AsyncTransport(base_url="http://testserver")
    transport._client = httpx.AsyncClient(transport=mock_transport, base_url="http://testserver")
    return AsyncServiceDeckClient(transport=transport)


# --- Sync Client Tests ---


def test_sync_list_and_add_devices() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/remote/devices":
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "srv1",
                        "display_name": "Web 1",
                        "hostname": "192.168.1.10",
                        "port": 22,
                        "username": "admin",
                        "connected": True,
                    }
                ],
            )
        if request.method == "POST" and request.url.path == "/api/remote/devices":
            return httpx.Response(
                201,
                json={
                    "id": "srv2",
                    "display_name": "Web 2",
                    "hostname": "192.168.1.20",
                    "port": 2222,
                    "username": "root",
                    "connected": False,
                },
            )
        return httpx.Response(404)

    client = create_mock_sync_client(handler)
    devices = client.list_devices()
    assert len(devices) == 1
    assert isinstance(devices[0], RemoteDevice)
    assert devices[0].id == "srv1"
    assert devices[0].connected is True

    added = client.add_device(id="srv2", hostname="192.168.1.20", port=2222, username="root")
    assert added.id == "srv2"
    assert added.port == 2222


def test_sync_connect_and_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/remote/devices/srv1/connect":
            return httpx.Response(
                200,
                json={
                    "device_id": "srv1",
                    "connected": True,
                    "remote_host": "srv1.local",
                    "remote_user": "admin",
                    "remote_uid": 1000,
                    "remote_version": "2.0.0",
                },
            )
        return httpx.Response(404)

    client = create_mock_sync_client(handler)
    info = client.connect_device("srv1")
    assert isinstance(info, RemoteConnectionInfo)
    assert info.connected is True
    assert info.remote_user == "admin"


def test_sync_remote_services_routing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Route should hit /api/remote/srv1/services
        if request.method == "GET" and request.url.path == "/api/remote/srv1/services":
            assert request.url.params.get("scope") == "system"
            return httpx.Response(
                200,
                json=[
                    {
                        "name": "nginx.service",
                        "description": "Nginx",
                        "load_state": "loaded",
                        "active_state": "active",
                        "sub_state": "running",
                        "unit_file_state": "enabled",
                        "scope": "system",
                    }
                ],
            )
        if request.method == "POST" and request.url.path == "/api/remote/srv1/services/nginx.service/restart":
            return httpx.Response(
                200,
                json={
                    "success": True,
                    "service": "nginx.service",
                    "operation": "restart",
                    "scope": "system",
                },
            )
        return httpx.Response(404)

    client = create_mock_sync_client(handler)

    # 1. Using explicit device_id parameter
    services = client.list_services(scope="system", device_id="srv1")
    assert len(services) == 1
    assert services[0].name == "nginx.service"

    # 2. Setting target_device on client
    client.target_device = "srv1"
    res = client.restart_service("nginx.service", scope="system")
    assert res.success is True
    assert res.operation == "restart"


# --- Async Client Tests ---


async def test_async_remote_services_routing() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/remote/node1/services/ssh.service":
            return httpx.Response(
                200,
                json={
                    "name": "ssh.service",
                    "description": "SSH",
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "unit_file_state": "enabled",
                    "scope": "system",
                },
            )
        return httpx.Response(404)

    client = create_mock_async_client(handler)
    svc = await client.get_service("ssh.service", device_id="node1")
    assert svc.name == "ssh.service"
