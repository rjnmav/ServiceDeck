"""Unit tests for remote device and service REST API endpoints."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings
from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    ServiceNotFoundError,
    SSHAuthenticationError,
)
from servicedeck.backend.models.service import Service, ServiceResourceUsage
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.remote.models import HelloMessage


@pytest.fixture
def mock_remote_manager() -> MagicMock:
    mgr = MagicMock(spec=RemoteManager)
    mgr.list_devices = MagicMock(return_value=[])
    mgr.get_device = MagicMock(return_value=None)
    mgr.add_device = MagicMock()
    mgr.remove_device = AsyncMock(return_value=True)
    mgr.connect = AsyncMock()
    mgr.disconnect = AsyncMock()
    mgr.disconnect_all = AsyncMock()
    mgr.is_connected = MagicMock(return_value=False)
    mgr.list_connected = MagicMock(return_value=[])
    mgr.list_services = AsyncMock()
    mgr.get_service = AsyncMock()
    mgr.start_service = AsyncMock()
    mgr.stop_service = AsyncMock()
    mgr.restart_service = AsyncMock()
    mgr.reload_service = AsyncMock()
    mgr.enable_service = AsyncMock()
    mgr.disable_service = AsyncMock()
    mgr.mask_service = AsyncMock()
    mgr.unmask_service = AsyncMock()
    mgr.reload_daemon = AsyncMock()
    mgr.get_unit_file = AsyncMock()
    mgr.get_service_resources = AsyncMock()
    mgr.get_service_logs = AsyncMock()
    mgr.create_service = AsyncMock()
    mgr.is_healthy = AsyncMock()

    mgr.connection_manager = MagicMock()
    mgr.connection_manager.get_transport = MagicMock(return_value=None)
    return mgr


@pytest.fixture
async def remote_client(
    service_manager: ServiceManager,
    mock_remote_manager: MagicMock,
    test_settings: Settings,
) -> AsyncClient:
    app = create_app(
        settings=test_settings,
        service_manager=service_manager,
        remote_manager=mock_remote_manager,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# --- Device endpoints tests ---


async def test_list_devices_empty(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    resp = await remote_client.get("/api/remote/devices")
    assert resp.status_code == 200
    assert resp.json() == []


async def test_add_device(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    saved_dev = RemoteDevice(
        id="box1",
        display_name="Production Box",
        hostname="10.0.0.1",
        port=22,
        username="deploy",
    )
    mock_remote_manager.add_device.return_value = saved_dev
    mock_remote_manager.is_connected.return_value = False

    payload = {
        "id": "box1",
        "display_name": "Production Box",
        "hostname": "10.0.0.1",
        "port": 22,
        "username": "deploy",
    }
    resp = await remote_client.post("/api/remote/devices", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["id"] == "box1"
    assert data["connected"] is False


async def test_remove_device_success(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.remove_device.return_value = True
    resp = await remote_client.delete("/api/remote/devices/box1")
    assert resp.status_code == 204
    mock_remote_manager.remove_device.assert_called_once_with("box1")


async def test_remove_device_not_found(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.remove_device.return_value = False
    resp = await remote_client.delete("/api/remote/devices/unknown")
    assert resp.status_code == 404


async def test_connect_device(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.connect.return_value = HelloMessage(
        host="box1",
        user="deploy",
        uid=1001,
        servicedeck_version="2.0.0",
    )
    resp = await remote_client.post("/api/remote/devices/box1/connect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["remote_user"] == "deploy"
    assert data["remote_uid"] == 1001


async def test_disconnect_device(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    resp = await remote_client.post("/api/remote/devices/box1/disconnect")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False
    mock_remote_manager.disconnect.assert_called_once_with("box1")


async def test_device_status(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.is_connected.return_value = True
    mock_transport = MagicMock()
    mock_transport.hello = HelloMessage(host="box1", user="deploy", uid=1001, servicedeck_version="2.0.0")
    mock_remote_manager.connection_manager.get_transport.return_value = mock_transport

    resp = await remote_client.get("/api/remote/devices/box1/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["remote_host"] == "box1"


# --- Remote Service Endpoints tests ---


async def test_list_remote_services(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.list_services.return_value = [
        Service(
            name="ssh.service",
            description="OpenSSH Server",
            load_state="loaded",
            active_state="active",
            sub_state="running",
            unit_file_state="enabled",
            scope="system",
        )
    ]

    resp = await remote_client.get("/api/remote/box1/services?scope=system")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["name"] == "ssh.service"
    mock_remote_manager.list_services.assert_called_once_with(device_id="box1", scope="system")


async def test_get_remote_service(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.get_service.return_value = Service(
        name="nginx.service",
        description="Nginx",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
        scope="system",
    )

    resp = await remote_client.get("/api/remote/box1/services/nginx.service")
    assert resp.status_code == 200
    assert resp.json()["name"] == "nginx.service"


async def test_remote_service_operations(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    operations = ["start", "stop", "restart", "reload", "enable", "disable", "mask", "unmask"]
    for op in operations:
        resp = await remote_client.post(f"/api/remote/box1/services/ssh.service/{op}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["operation"] == op


async def test_remote_daemon_reload(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    resp = await remote_client.post("/api/remote/box1/daemon/reload")
    assert resp.status_code == 200
    assert resp.json()["success"] is True


async def test_remote_unit_file(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.get_unit_file.return_value = ("/etc/systemd/system/ssh.service", "[Unit]\n")
    resp = await remote_client.get("/api/remote/box1/services/ssh.service/unit-file")
    assert resp.status_code == 200
    assert resp.json()["fragment_path"] == "/etc/systemd/system/ssh.service"


async def test_remote_resources(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.get_service_resources.return_value = ServiceResourceUsage(
        service="ssh.service",
        scope="system",
        is_active=True,
        memory_current=2048,
        cpu_usage_nsec=1000,
    )
    resp = await remote_client.get("/api/remote/box1/services/ssh.service/resources")
    assert resp.status_code == 200
    assert resp.json()["memory_current_bytes"] == 2048


async def test_remote_logs(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.get_service_logs.return_value = "log line 1\nlog line 2\n"
    resp = await remote_client.get("/api/remote/box1/services/ssh.service/logs?lines=50")
    assert resp.status_code == 200
    assert "log line 1" in resp.json()["logs"]


async def test_remote_health(remote_client: AsyncClient, mock_remote_manager: MagicMock) -> None:
    mock_remote_manager.is_healthy.return_value = True
    resp = await remote_client.get("/api/remote/box1/health")
    assert resp.status_code == 200
    assert resp.json()["healthy"] is True


# --- Remote Exception Handling in FastAPI ---


async def test_remote_service_not_found_mapped_to_404(
    remote_client: AsyncClient, mock_remote_manager: MagicMock
) -> None:
    mock_remote_manager.get_service.side_effect = ServiceNotFoundError("missing.service")
    resp = await remote_client.get("/api/remote/box1/services/missing.service")
    assert resp.status_code == 404
    assert resp.json()["error"] == "ServiceNotFoundError"


async def test_remote_connection_error_mapped_to_502(
    remote_client: AsyncClient, mock_remote_manager: MagicMock
) -> None:
    mock_remote_manager.list_services.side_effect = RemoteConnectionError("Host unreachable")
    resp = await remote_client.get("/api/remote/box1/services")
    assert resp.status_code == 502
    assert resp.json()["error"] == "RemoteConnectionError"


async def test_remote_auth_error_mapped_to_401(
    remote_client: AsyncClient, mock_remote_manager: MagicMock
) -> None:
    mock_remote_manager.connect.side_effect = SSHAuthenticationError("Invalid credentials")
    resp = await remote_client.post("/api/remote/devices/box1/connect")
    assert resp.status_code == 401
    assert resp.json()["error"] == "SSHAuthenticationError"
