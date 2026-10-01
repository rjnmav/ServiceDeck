"""Unit tests for ServiceManager business logic and active scope handling."""

import pytest
from tests.conftest import FakeSystemdAdapter

from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    PermissionDeniedError,
    ServiceNotFoundError,
    ServiceOperationError,
)


async def test_active_scope_default_and_toggle(service_manager: ServiceManager) -> None:
    assert service_manager.active_scope == "user"
    assert service_manager.get_active_scope() == "user"

    service_manager.set_active_scope("system")
    assert service_manager.active_scope == "system"
    assert service_manager.get_active_scope() == "system"

    service_manager.set_active_scope("user")
    assert service_manager.active_scope == "user"


async def test_list_services_default_user_scope(service_manager: ServiceManager) -> None:
    # By default, lists user services
    services = await service_manager.list_services()
    assert len(services) == 3
    names = [s.name for s in services]
    assert "pipewire.service" in names
    assert "plasma-runner.service" in names
    assert "user-test.service" in names
    assert all(s.scope == "user" for s in services)


async def test_list_services_toggled_system_scope(service_manager: ServiceManager) -> None:
    # Toggle to system
    service_manager.set_active_scope("system")
    services = await service_manager.list_services()
    assert len(services) == 3
    names = [s.name for s in services]
    assert "ssh.service" in names
    assert "nginx.service" in names
    assert "broken.service" in names
    assert all(s.scope == "system" for s in services)


async def test_list_services_explicit_scope_override(service_manager: ServiceManager) -> None:
    # Active is user, but we explicitly pass scope="system"
    assert service_manager.active_scope == "user"
    services = await service_manager.list_services(scope="system")
    names = [s.name for s in services]
    assert "ssh.service" in names
    assert all(s.scope == "system" for s in services)


async def test_get_service_success(service_manager: ServiceManager) -> None:
    # User scope by default
    svc = await service_manager.get_service("pipewire")
    assert svc.name == "pipewire.service"
    assert svc.scope == "user"
    assert svc.active_state == "active"
    assert svc.is_running is True

    # System scope explicit
    sys_svc = await service_manager.get_service("ssh", scope="system")
    assert sys_svc.name == "ssh.service"
    assert sys_svc.scope == "system"


async def test_get_service_not_found(service_manager: ServiceManager) -> None:
    # Looking for a system service in user scope should raise not found
    with pytest.raises(ServiceNotFoundError):
        await service_manager.get_service("ssh.service")


async def test_start_service(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    # Initially inactive user service
    svc = await service_manager.get_service("user-test")
    assert svc.active_state == "inactive"

    await service_manager.start_service("user-test")

    svc_after = await service_manager.get_service("user-test")
    assert svc_after.active_state == "active"
    assert svc_after.sub_state == "running"
    assert ("start_service", "user-test.service", "user") in fake_adapter.calls


async def test_stop_service(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    svc = await service_manager.get_service("plasma-runner")
    assert svc.active_state == "active"

    await service_manager.stop_service("plasma-runner")

    svc_after = await service_manager.get_service("plasma-runner")
    assert svc_after.active_state == "inactive"
    assert svc_after.sub_state == "dead"
    assert ("stop_service", "plasma-runner.service", "user") in fake_adapter.calls


async def test_restart_service(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    await service_manager.restart_service("pipewire")
    svc_after = await service_manager.get_service("pipewire")
    assert svc_after.active_state == "active"
    assert ("restart_service", "pipewire.service", "user") in fake_adapter.calls


async def test_reload_service(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    await service_manager.reload_service("pipewire")
    assert ("reload_service", "pipewire.service", "user") in fake_adapter.calls


async def test_enable_disable_service(service_manager: ServiceManager) -> None:
    svc = await service_manager.get_service("user-test")
    assert svc.unit_file_state == "disabled"

    await service_manager.enable_service("user-test")
    svc_enabled = await service_manager.get_service("user-test")
    assert svc_enabled.unit_file_state == "enabled"

    await service_manager.disable_service("user-test")
    svc_disabled = await service_manager.get_service("user-test")
    assert svc_disabled.unit_file_state == "disabled"


async def test_permission_denied_handling(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    service_manager.set_active_scope("system")
    fake_adapter.denied_operations.add(("start", "system"))
    with pytest.raises(PermissionDeniedError) as exc_info:
        await service_manager.start_service("nginx")
    assert exc_info.value.action == "start"


async def test_service_operation_error_handling(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    fake_adapter.failing_operations.add(("start", "user"))
    with pytest.raises(ServiceOperationError) as exc_info:
        await service_manager.start_service("user-test")
    assert exc_info.value.operation == "start"


async def test_is_healthy(
    service_manager: ServiceManager, fake_adapter: FakeSystemdAdapter
) -> None:
    assert await service_manager.is_healthy("user") is True
    assert await service_manager.is_healthy("system") is True

    fake_adapter.healthy_scopes["user"] = False
    assert await service_manager.is_healthy("user") is False
    assert await service_manager.is_healthy("system") is True
