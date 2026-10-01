"""Unit tests for the /api/services REST endpoints supporting user and system scopes."""

from httpx import AsyncClient
from tests.conftest import FakeSystemdAdapter


async def test_list_services_endpoint_default_user(client: AsyncClient) -> None:
    response = await client.get("/api/services")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 3
    names = [s["name"] for s in data]
    assert "pipewire.service" in names
    assert "plasma-runner.service" in names
    assert all(s["scope"] == "user" for s in data)


async def test_list_services_endpoint_system_override(client: AsyncClient) -> None:
    response = await client.get("/api/services?scope=system")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 3
    names = [s["name"] for s in data]
    assert "ssh.service" in names
    assert "nginx.service" in names
    assert all(s["scope"] == "system" for s in data)


async def test_get_service_endpoint_user_default(client: AsyncClient) -> None:
    response = await client.get("/api/services/pipewire.service")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "pipewire.service"
    assert data["scope"] == "user"
    assert data["load_state"] == "loaded"
    assert data["active_state"] == "active"
    assert data["sub_state"] == "running"
    assert data["unit_file_state"] == "enabled"


async def test_get_service_endpoint_system_explicit(client: AsyncClient) -> None:
    response = await client.get("/api/services/ssh.service?scope=system")
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "ssh.service"
    assert data["scope"] == "system"


async def test_get_service_endpoint_without_suffix(client: AsyncClient) -> None:
    response = await client.get("/api/services/pipewire")
    assert response.status_code == 200
    assert response.json()["name"] == "pipewire.service"


async def test_get_service_endpoint_not_found(client: AsyncClient) -> None:
    response = await client.get("/api/services/nonexistent.service")
    assert response.status_code == 404
    data = response.json()
    assert data["error"] == "ServiceNotFoundError"
    assert "not found" in data["message"]


async def test_get_service_endpoint_invalid_name(client: AsyncClient) -> None:
    response = await client.get("/api/services/bad%20name%20with%20spaces")
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "InvalidServiceNameError"


async def test_start_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/user-test/start")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "start"
    assert data["scope"] == "user"
    assert data["service"] == "user-test"

    get_res = await client.get("/api/services/user-test")
    assert get_res.json()["active_state"] == "active"


async def test_stop_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/plasma-runner/stop")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "stop"
    assert data["scope"] == "user"

    get_res = await client.get("/api/services/plasma-runner")
    assert get_res.json()["active_state"] == "inactive"


async def test_restart_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/user-test/restart")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "restart"


async def test_reload_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/pipewire/reload")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "reload"


async def test_enable_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/user-test/enable")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "enable"

    get_res = await client.get("/api/services/user-test")
    assert get_res.json()["unit_file_state"] == "enabled"


async def test_disable_service_endpoint(client: AsyncClient) -> None:
    response = await client.post("/api/services/pipewire/disable")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "disable"

    get_res = await client.get("/api/services/pipewire")
    assert get_res.json()["unit_file_state"] == "disabled"


async def test_system_service_operation(client: AsyncClient) -> None:
    response = await client.post("/api/services/nginx/start?scope=system")
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert data["operation"] == "start"
    assert data["scope"] == "system"


async def test_permission_denied_endpoint(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.denied_operations.add(("start", "system"))
    response = await client.post("/api/services/nginx/start?scope=system")
    assert response.status_code == 403
    data = response.json()
    assert data["error"] == "PermissionDeniedError"
    assert "Permission denied" in data["message"]


async def test_service_operation_error_endpoint(
    client: AsyncClient, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.failing_operations.add(("start", "user"))
    response = await client.post("/api/services/user-test/start")
    assert response.status_code == 400
    data = response.json()
    assert data["error"] == "ServiceOperationError"
    assert "Failed to start" in data["message"]


async def test_mask_and_unmask_service_endpoint(client: AsyncClient) -> None:
    # Mask service
    mask_res = await client.post("/api/services/user-test/mask")
    assert mask_res.status_code == 200
    data = mask_res.json()
    assert data["success"] is True
    assert data["operation"] == "mask"

    get_res = await client.get("/api/services/user-test")
    assert get_res.json()["unit_file_state"] == "masked"

    # Unmask service
    unmask_res = await client.post("/api/services/user-test/unmask")
    assert unmask_res.status_code == 200
    data = unmask_res.json()
    assert data["success"] is True
    assert data["operation"] == "unmask"

    get_res2 = await client.get("/api/services/user-test")
    assert get_res2.json()["unit_file_state"] == "disabled"


async def test_get_unit_file_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/services/pipewire/unit-file")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "pipewire.service"
    assert data["fragment_path"] is not None
    assert "Description=" in data["content"]
    assert data["scope"] == "user"


async def test_get_service_resources_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/services/pipewire/resources")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "pipewire.service"
    assert data["cpu_usage_nsec"] == 1_500_000_000
    assert data["memory_current_bytes"] == 104_857_600
    assert data["disk_read_bytes"] == 10240
    assert data["disk_write_bytes"] == 20480
    assert data["tasks_current"] == 4
    assert data["main_pid"] == 1234
    assert data["active_state"] == "active"


async def test_get_service_logs_endpoint(client: AsyncClient) -> None:
    response = await client.get("/api/services/pipewire/logs?lines=50")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "pipewire.service"
    assert "Started pipewire.service" in data["logs"]
    assert data["lines"] == 50


async def test_create_service_endpoint(client: AsyncClient) -> None:
    payload = {
        "name": "custom-task.service",
        "content": "[Unit]\nDescription=Custom Task\n[Service]\nExecStart=/bin/echo hello\n",
        "scope": "user",
        "overwrite": True,
    }
    response = await client.post("/api/services/create", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["success"] is True
    assert data["service"] == "custom-task.service"
    assert "custom-task.service" in data["path"]
    assert data["scope"] == "user"

    # Verify newly created service appears in list
    list_res = await client.get("/api/services")
    names = [s["name"] for s in list_res.json()]
    assert "custom-task.service" in names
