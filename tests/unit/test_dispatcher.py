"""Unit tests for remote agent RequestDispatcher."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    PolkitAgentUnavailableError,
    ServiceNotFoundError,
    SystemdConnectionError,
)
from servicedeck.backend.models.service import Service, ServiceResourceUsage
from servicedeck.backend.models.unit_files import (
    DropIn,
    OverrideResult,
    UnitFileInfo,
    override_result_from_dict,
    unit_info_from_dict,
)
from servicedeck.remote.models import RequestMessage
from servicedeck.remote_agent.dispatcher import RequestDispatcher


@pytest.fixture
def mock_service_manager() -> MagicMock:
    """Mock ServiceManager providing async method doubles."""
    manager = MagicMock()
    manager.list_services = AsyncMock()
    manager.get_service = AsyncMock()
    manager.start_service = AsyncMock()
    manager.stop_service = AsyncMock()
    manager.restart_service = AsyncMock()
    manager.reload_service = AsyncMock()
    manager.enable_service = AsyncMock()
    manager.disable_service = AsyncMock()
    manager.mask_service = AsyncMock()
    manager.unmask_service = AsyncMock()
    manager.reload_daemon = AsyncMock()
    manager.get_unit_file = AsyncMock()
    manager.get_service_resources = AsyncMock()
    manager.get_service_logs = AsyncMock()
    manager.create_service = AsyncMock()
    manager.is_healthy = AsyncMock()
    return manager


@pytest.fixture
def dispatcher(mock_service_manager: MagicMock) -> RequestDispatcher:
    return RequestDispatcher(mock_service_manager)


_DUMMY_SERVICE = Service(
    name="nginx.service",
    description="Nginx HTTP Server",
    load_state="loaded",
    active_state="active",
    sub_state="running",
    unit_file_state="enabled",
    scope="system",
)


async def test_dispatch_service_list(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.list_services.return_value = [_DUMMY_SERVICE]
    req = RequestMessage(id=1, method="service.list", params={"scope": "system"})

    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.id == 1
    assert len(resp.result) == 1
    assert resp.result[0]["name"] == "nginx.service"
    mock_service_manager.list_services.assert_called_once_with(scope="system")


async def test_dispatch_service_get(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.get_service.return_value = _DUMMY_SERVICE
    req = RequestMessage(id=2, method="service.get", params={"name": "nginx", "scope": "system"})

    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result["name"] == "nginx.service"
    mock_service_manager.get_service.assert_called_once_with(name="nginx", scope="system")


async def test_dispatch_service_lifecycle_methods(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    lifecycle_methods = [
        ("service.start", mock_service_manager.start_service),
        ("service.stop", mock_service_manager.stop_service),
        ("service.restart", mock_service_manager.restart_service),
        ("service.reload", mock_service_manager.reload_service),
        ("service.enable", mock_service_manager.enable_service),
        ("service.disable", mock_service_manager.disable_service),
        ("service.mask", mock_service_manager.mask_service),
        ("service.unmask", mock_service_manager.unmask_service),
    ]

    for req_id, (method, mock_call) in enumerate(lifecycle_methods, start=10):
        req = RequestMessage(id=req_id, method=method, params={"name": "ssh", "scope": "user"})
        resp = await dispatcher.dispatch(req)
        assert resp.success is True
        assert resp.result is None
        mock_call.assert_called_once_with(name="ssh", scope="user")


async def test_dispatch_daemon_reload(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    req = RequestMessage(id=30, method="daemon.reload", params={"scope": "system"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    mock_service_manager.reload_daemon.assert_called_once_with(scope="system")


async def test_dispatch_unit_file(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.get_unit_file.return_value = (
        "/lib/systemd/system/ssh.service",
        "[Unit]\n",
    )
    req = RequestMessage(id=31, method="service.unit_file", params={"name": "ssh"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result == {"path": "/lib/systemd/system/ssh.service", "content": "[Unit]\n"}


async def test_dispatch_service_resources(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    usage = ServiceResourceUsage(
        service="ssh.service",
        scope="system",
        is_active=True,
        cpu_usage_nsec=12345,
        memory_current=67890,
    )
    mock_service_manager.get_service_resources.return_value = usage
    req = RequestMessage(id=32, method="service.resources", params={"name": "ssh"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result["service"] == "ssh.service"
    assert resp.result["cpu_usage_nsec"] == 12345


async def test_dispatch_service_logs(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.get_service_logs.return_value = "line 1\nline 2\n"
    req = RequestMessage(id=33, method="service.logs", params={"name": "ssh", "lines": 50})
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result == {"logs": "line 1\nline 2\n"}
    mock_service_manager.get_service_logs.assert_called_once_with(name="ssh", lines=50, scope=None)


async def test_dispatch_create_service(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.create_service.return_value = "/etc/systemd/system/custom.service"
    req = RequestMessage(
        id=34,
        method="service.create",
        params={"name": "custom", "content": "[Service]\nExecStart=/bin/true"},
    )
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result == {"path": "/etc/systemd/system/custom.service"}


async def test_dispatch_health_check(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.is_healthy.return_value = True
    req = RequestMessage(id=35, method="health.check")
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result == {"healthy": True}


# --- Error dispatching tests ---


async def test_dispatch_unknown_method(dispatcher: RequestDispatcher) -> None:
    req = RequestMessage(id=50, method="unknown.action")
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.code == "INVALID_PARAMS"


async def test_dispatch_missing_required_param(dispatcher: RequestDispatcher) -> None:
    req = RequestMessage(id=51, method="service.start", params={})  # Missing 'name'
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.code == "INVALID_PARAMS"
    assert "name" in resp.error.message


async def test_dispatch_service_not_found_error(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.get_service.side_effect = ServiceNotFoundError("missing.service")
    req = RequestMessage(id=52, method="service.get", params={"name": "missing"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error.code == "SERVICE_NOT_FOUND"
    assert resp.error.details == {"service_name": "missing.service"}


async def test_dispatch_polkit_agent_unavailable_error(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.restart_service.side_effect = PolkitAgentUnavailableError(
        action="restart", service_name="nginx", scope="system"
    )
    req = RequestMessage(id=53, method="service.restart", params={"name": "nginx"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error.code == "AUTHENTICATION_REQUIRED"
    assert resp.error.details["action"] == "restart"


async def test_dispatch_authorization_denied_error(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.stop_service.side_effect = AuthorizationDeniedError(
        action="stop", service_name="ssh"
    )
    req = RequestMessage(id=54, method="service.stop", params={"name": "ssh"})
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error.code == "AUTHORIZATION_DENIED"


async def test_dispatch_systemd_connection_error(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.list_services.side_effect = SystemdConnectionError("D-Bus down")
    req = RequestMessage(id=55, method="service.list")
    resp = await dispatcher.dispatch(req)
    assert resp.success is False
    assert resp.error.code == "SYSTEMD_CONNECTION_ERROR"


# --- Unit files and drop-in overrides ---


async def test_dispatch_unit_info_round_trips_through_remote_manager_model(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    info = UnitFileInfo(
        service="ssh.service",
        scope="system",
        fragment_path="/usr/lib/systemd/system/ssh.service",
        content="[Unit]\n",
        drop_ins=[DropIn("/etc/systemd/system/ssh.service.d/override.conf", "[Service]\n", True)],
        override_path="/etc/systemd/system/ssh.service.d/override.conf",
        need_daemon_reload=True,
    )
    mock_service_manager.get_unit_info = AsyncMock(return_value=info)
    req = RequestMessage(
        id=40, method="service.unit_info", params={"name": "ssh", "scope": "system"}
    )
    resp = await dispatcher.dispatch(req)
    assert resp.success is True
    assert resp.result["drop_ins"][0]["editable"] is True
    # What RemoteManager rebuilds from the JSON is the original value.
    assert unit_info_from_dict(resp.result) == info


async def test_dispatch_override_write_and_revert(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    result = OverrideResult(
        "ssh.service", "system", "/etc/systemd/system/ssh.service.d/override.conf", warnings=["w"]
    )
    mock_service_manager.write_override = AsyncMock(return_value=result)
    mock_service_manager.revert_overrides = AsyncMock(return_value=["/etc/x.conf"])

    resp = await dispatcher.dispatch(
        RequestMessage(
            id=41,
            method="service.override.write",
            params={"name": "ssh", "content": "[Service]\nNice=5\n", "scope": "system"},
        )
    )
    assert resp.success is True
    assert override_result_from_dict(resp.result) == result
    mock_service_manager.write_override.assert_awaited_once_with(
        name="ssh", content="[Service]\nNice=5\n", scope="system", drop_in="override.conf"
    )

    resp = await dispatcher.dispatch(
        RequestMessage(id=42, method="service.override.revert", params={"name": "ssh"})
    )
    assert resp.result == {"removed": ["/etc/x.conf"]}


async def test_dispatch_override_permission_error_is_an_elevation_code(
    dispatcher: RequestDispatcher, mock_service_manager: MagicMock
) -> None:
    mock_service_manager.write_override = AsyncMock(
        side_effect=AuthorizationDeniedError(action="edit", service_name="ssh.service")
    )
    resp = await dispatcher.dispatch(
        RequestMessage(
            id=43,
            method="service.override.write",
            params={"name": "ssh", "content": "[Service]\n", "scope": "system"},
        )
    )
    assert resp.success is False
    assert resp.error is not None
    assert resp.error.code == "AUTHORIZATION_DENIED"


async def test_dispatch_override_write_requires_content(dispatcher: RequestDispatcher) -> None:
    resp = await dispatcher.dispatch(
        RequestMessage(id=44, method="service.override.write", params={"name": "ssh"})
    )
    assert resp.success is False
