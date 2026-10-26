"""Unit tests for RemoteManager."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    InvalidServiceNameError,
    RemoteConnectionError,
    ServiceNotFoundError,
    ServiceOperationError,
    SystemdConnectionError,
)
from servicedeck.backend.models.service import Service, ServiceResourceUsage
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.remote.models import (
    HelloMessage,
    error_response,
    success_response,
)


@pytest.fixture
def test_device() -> RemoteDevice:
    return RemoteDevice(
        id="dev1",
        display_name="Device 1",
        hostname="dev1.local",
        port=22,
        username="admin",
    )


@pytest.fixture
def mock_conn_mgr() -> MagicMock:
    conn_mgr = MagicMock()
    conn_mgr.connect = AsyncMock()
    conn_mgr.disconnect = AsyncMock()
    conn_mgr.disconnect_all = AsyncMock()
    conn_mgr.is_connected = MagicMock(return_value=False)
    conn_mgr.list_connected = MagicMock(return_value=[])
    conn_mgr.get_transport = MagicMock(return_value=None)
    return conn_mgr


@pytest.fixture
def mock_cfg_mgr(test_device: RemoteDevice) -> MagicMock:
    cfg = MagicMock()
    cfg.load_devices = MagicMock(return_value=[test_device])
    cfg.get_device = MagicMock(side_effect=lambda dev_id: test_device if dev_id == "dev1" else None)
    cfg.save_device = MagicMock()
    cfg.remove_device = MagicMock(return_value=True)
    return cfg


@pytest.fixture
def remote_manager(mock_conn_mgr: MagicMock, mock_cfg_mgr: MagicMock) -> RemoteManager:
    return RemoteManager(connection_manager=mock_conn_mgr, config_manager=mock_cfg_mgr)


# --- Device Configuration CRUD ---


def test_device_crud(remote_manager: RemoteManager, test_device: RemoteDevice, mock_cfg_mgr: MagicMock) -> None:
    assert remote_manager.list_devices() == [test_device]
    assert remote_manager.get_device("dev1") == test_device
    assert remote_manager.get_device("nonexistent") is None

    new_device = RemoteDevice(id="dev2", display_name="Device 2", hostname="dev2.local")
    remote_manager.add_device(new_device)
    mock_cfg_mgr.save_device.assert_called_once_with(new_device)


async def test_remove_device_disconnects(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock, mock_cfg_mgr: MagicMock
) -> None:
    res = await remote_manager.remove_device("dev1")
    assert res is True
    mock_conn_mgr.disconnect.assert_called_once_with("dev1")
    mock_cfg_mgr.remove_device.assert_called_once_with("dev1")


# --- Connection Lifecycle ---


async def test_connect(
    remote_manager: RemoteManager, test_device: RemoteDevice, mock_conn_mgr: MagicMock
) -> None:
    hello = HelloMessage(host="dev1", user="admin", uid=1000)
    mock_conn_mgr.connect.return_value = hello

    result = await remote_manager.connect("dev1")
    assert result == hello
    mock_conn_mgr.connect.assert_called_once_with(test_device, timeout=15.0)


async def test_connect_unknown_device(remote_manager: RemoteManager) -> None:
    with pytest.raises(RemoteConnectionError, match="not configured"):
        await remote_manager.connect("unknown_device")


async def test_disconnect_and_status(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    await remote_manager.disconnect("dev1")
    mock_conn_mgr.disconnect.assert_called_once_with("dev1")

    await remote_manager.disconnect_all()
    mock_conn_mgr.disconnect_all.assert_called_once()


# --- Remote Operations & Exception Mapping ---


async def test_list_services_success(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    mock_transport = MagicMock()
    mock_transport.is_connected = True
    mock_transport.send_request = AsyncMock(
        return_value=success_response(
            1,
            result=[
                {
                    "name": "ssh.service",
                    "description": "SSH Daemon",
                    "load_state": "loaded",
                    "active_state": "active",
                    "sub_state": "running",
                    "unit_file_state": "enabled",
                    "scope": "system",
                }
            ],
        )
    )
    mock_conn_mgr.get_transport.return_value = mock_transport

    services = await remote_manager.list_services("dev1", scope="system")
    assert len(services) == 1
    assert services[0].name == "ssh.service"
    assert isinstance(services[0], Service)


async def test_get_service_success(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    mock_transport = MagicMock()
    mock_transport.is_connected = True
    mock_transport.send_request = AsyncMock(
        return_value=success_response(
            1,
            result={
                "name": "nginx.service",
                "description": "Nginx Web Server",
                "load_state": "loaded",
                "active_state": "active",
                "sub_state": "running",
                "unit_file_state": "enabled",
                "scope": "system",
            },
        )
    )
    mock_conn_mgr.get_transport.return_value = mock_transport

    svc = await remote_manager.get_service("dev1", "nginx")
    assert svc.name == "nginx.service"
    assert svc.is_active is True


async def test_remote_exception_mapping(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    mock_transport = MagicMock()
    mock_transport.is_connected = True
    mock_conn_mgr.get_transport.return_value = mock_transport

    # SERVICE_NOT_FOUND
    mock_transport.send_request = AsyncMock(
        return_value=error_response(1, "SERVICE_NOT_FOUND", "Unit missing.service not found")
    )
    with pytest.raises(ServiceNotFoundError):
        await remote_manager.get_service("dev1", "missing")

    # INVALID_SERVICE_NAME
    mock_transport.send_request = AsyncMock(
        return_value=error_response(2, "INVALID_SERVICE_NAME", "Bad unit name")
    )
    with pytest.raises(InvalidServiceNameError):
        await remote_manager.get_service("dev1", "bad!")

    # AUTHENTICATION_REQUIRED
    mock_transport.send_request = AsyncMock(
        return_value=error_response(3, "AUTHENTICATION_REQUIRED", "Polkit prompt needed")
    )
    with pytest.raises(AuthenticationRequiredError):
        await remote_manager.start_service("dev1", "system-unit")

    # AUTHORIZATION_DENIED
    mock_transport.send_request = AsyncMock(
        return_value=error_response(4, "AUTHORIZATION_DENIED", "Access denied by polkit")
    )
    with pytest.raises(AuthorizationDeniedError):
        await remote_manager.stop_service("dev1", "protected")

    # SERVICE_OPERATION_FAILED
    mock_transport.send_request = AsyncMock(
        return_value=error_response(5, "SERVICE_OPERATION_FAILED", "Unit is masked")
    )
    with pytest.raises(ServiceOperationError):
        await remote_manager.restart_service("dev1", "masked")

    # SYSTEMD_CONNECTION_ERROR
    mock_transport.send_request = AsyncMock(
        return_value=error_response(6, "SYSTEMD_CONNECTION_ERROR", "D-Bus down")
    )
    with pytest.raises(SystemdConnectionError):
        await remote_manager.list_services("dev1")


async def test_remote_resource_and_logs(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    mock_transport = MagicMock()
    mock_transport.is_connected = True
    mock_conn_mgr.get_transport.return_value = mock_transport

    # Resources
    mock_transport.send_request = AsyncMock(
        return_value=success_response(
            1,
            result={
                "service": "ssh.service",
                "scope": "system",
                "is_active": True,
                "memory_current": 1048576,
            },
        )
    )
    res = await remote_manager.get_service_resources("dev1", "ssh")
    assert isinstance(res, ServiceResourceUsage)
    assert res.memory_current == 1048576

    # Logs
    mock_transport.send_request = AsyncMock(
        return_value=success_response(2, result={"logs": "log row 1\nlog row 2"})
    )
    logs = await remote_manager.get_service_logs("dev1", "ssh", lines=10)
    assert "log row 1" in logs


async def test_health_check(
    remote_manager: RemoteManager, mock_conn_mgr: MagicMock
) -> None:
    mock_transport = MagicMock()
    mock_transport.is_connected = True
    mock_transport.send_request = AsyncMock(return_value=success_response(1, result={"healthy": True}))
    mock_conn_mgr.get_transport.return_value = mock_transport

    healthy = await remote_manager.is_healthy("dev1")
    assert healthy is True
