"""Tests for the synchronous ServiceDeckClient using mock HTTP transports."""

import httpx

from servicedeck.api_client import (
    HealthInfo,
    ScopeInfo,
    Service,
    ServiceDeckClient,
    ServiceOperationResult,
)
from servicedeck.api_client.transport import SyncTransport


def create_mock_client(handler) -> ServiceDeckClient:
    """Helper to instantiate a ServiceDeckClient with httpx.MockTransport."""
    mock_transport = httpx.MockTransport(handler)
    transport = SyncTransport(base_url="http://testserver")
    transport._client = httpx.Client(transport=mock_transport, base_url="http://testserver")
    return ServiceDeckClient(transport=transport)


def test_health():
    """Test health endpoint query."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/health"
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "systemd_connected": True,
                "systemd_user_connected": True,
                "systemd_system_connected": True,
                "active_scope": "user",
                "version": "2.0.0",
            },
        )

    client = create_mock_client(handler)
    health = client.health()
    assert isinstance(health, HealthInfo)
    assert health.status == "ok"
    assert health.systemd_connected is True
    assert health.active_scope == "user"


def test_get_scope():
    """Test get_scope query."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/scope"
        return httpx.Response(
            200,
            json={"active_scope": "user", "available_scopes": ["user", "system"]},
        )

    client = create_mock_client(handler)
    scope_info = client.get_scope()
    assert isinstance(scope_info, ScopeInfo)
    assert scope_info.active_scope == "user"
    assert scope_info.available_scopes == ["user", "system"]


def test_set_scope():
    """Test set_scope mutation."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/scope"
        import json

        body = json.loads(request.content)
        assert body == {"scope": "system"}
        return httpx.Response(
            200,
            json={"active_scope": "system", "available_scopes": ["user", "system"]},
        )

    client = create_mock_client(handler)
    scope_info = client.set_scope("system")
    assert scope_info.active_scope == "system"


def test_list_services():
    """Test listing services with scope query parameter."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/services"
        assert request.url.query.decode() == "scope=user"
        return httpx.Response(
            200,
            json=[
                {
                    "name": "pipewire.service",
                    "description": "PipeWire Multimedia Service",
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "unit_file_state": "enabled",
                    "scope": "user",
                }
            ],
        )

    client = create_mock_client(handler)
    services = client.list_services(scope="user")
    assert len(services) == 1
    svc = services[0]
    assert isinstance(svc, Service)
    assert svc.name == "pipewire.service"
    assert svc.is_active is True
    assert svc.is_running is True
    assert svc.is_enabled is True
    assert svc.is_failed is False


def test_get_service():
    """Test getting single service details."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/services/dbus.service"
        return httpx.Response(
            200,
            json={
                "name": "dbus.service",
                "description": "D-Bus User Message Bus",
                "load_state": "loaded",
                "active_state": "active",
                "sub_state": "running",
                "unit_file_state": "static",
                "scope": "user",
            },
        )

    client = create_mock_client(handler)
    svc = client.get_service("dbus.service")
    assert svc.name == "dbus.service"
    assert svc.unit_file_state == "static"


def test_service_operations():
    """Test start, stop, restart, reload, enable, disable operations."""
    ops_called = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = path.strip("/").split("/")
        # format: api/services/{name}/{op}
        op = parts[-1]
        name = parts[-2]
        ops_called.append((op, name))
        return httpx.Response(
            200,
            json={
                "success": True,
                "service": name,
                "operation": op,
                "scope": "user",
                "message": f"Service {name} {op} successful",
            },
        )

    client = create_mock_client(handler)
    res_start = client.start_service("app.service")
    assert isinstance(res_start, ServiceOperationResult)
    assert res_start.success is True
    assert res_start.operation == "start"

    client.stop_service("app.service")
    client.restart_service("app.service")
    client.reload_service("app.service")
    client.enable_service("app.service")
    client.disable_service("app.service")

    assert [op[0] for op in ops_called] == [
        "start",
        "stop",
        "restart",
        "reload",
        "enable",
        "disable",
    ]


def test_mask_and_unmask_service():
    ops_called = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        parts = path.strip("/").split("/")
        op = parts[-1]
        name = parts[-2]
        ops_called.append((op, name))
        return httpx.Response(
            200,
            json={
                "success": True,
                "service": name,
                "operation": op,
                "scope": "user",
                "message": f"Service {name} {op} successful",
            },
        )

    client = create_mock_client(handler)
    res_mask = client.mask_service("app.service")
    assert res_mask.success is True
    assert res_mask.operation == "mask"

    res_unmask = client.unmask_service("app.service")
    assert res_unmask.success is True
    assert res_unmask.operation == "unmask"
    assert [op[0] for op in ops_called] == ["mask", "unmask"]


def test_reload_daemon():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/daemon/reload"
        return httpx.Response(
            200,
            json={"success": True, "scope": "user", "message": "reloaded"},
        )

    client = create_mock_client(handler)
    res = client.reload_daemon()
    assert res.success is True
    assert res.scope == "user"


def test_get_unit_file():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/services/app.service/unit-file"
        return httpx.Response(
            200,
            json={
                "service": "app.service",
                "fragment_path": "/etc/systemd/system/app.service",
                "content": "[Unit]\nDescription=App\n",
                "scope": "system",
            },
        )

    client = create_mock_client(handler)
    unit_file = client.get_unit_file("app.service")
    assert unit_file.service == "app.service"
    assert unit_file.fragment_path == "/etc/systemd/system/app.service"
    assert "[Unit]" in unit_file.content


def test_get_resources():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/services/app.service/resources"
        return httpx.Response(
            200,
            json={
                "service": "app.service",
                "cpu_usage_nsec": 2000000000,
                "memory_current_bytes": 52428800,
                "disk_read_bytes": 1000,
                "disk_write_bytes": 2000,
                "tasks_current": 8,
                "main_pid": 4567,
                "active_enter_timestamp": 1700000000000000,
                "active_state": "active",
                "scope": "user",
            },
        )

    client = create_mock_client(handler)
    res = client.get_resources("app.service")
    assert res.service == "app.service"
    assert res.cpu_usage_nsec == 2000000000
    assert res.memory_current_bytes == 52428800
    assert res.main_pid == 4567


def test_get_logs():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/services/app.service/logs"
        assert "lines=100" in request.url.query.decode()
        return httpx.Response(
            200,
            json={
                "service": "app.service",
                "logs": "log line 1\nlog line 2",
                "scope": "user",
                "lines": 100,
            },
        )

    client = create_mock_client(handler)
    logs = client.get_logs("app.service", lines=100)
    assert logs.service == "app.service"
    assert "log line 1" in logs.logs


def test_create_service():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/services/create"
        import json

        body = json.loads(request.content)
        assert body["name"] == "new.service"
        return httpx.Response(
            200,
            json={
                "success": True,
                "service": "new.service",
                "path": "/home/user/.config/systemd/user/new.service",
                "scope": "user",
            },
        )

    client = create_mock_client(handler)
    created = client.create_service(name="new.service", content="[Unit]\n")
    assert created.success is True
    assert created.service == "new.service"
    assert "new.service" in created.path
