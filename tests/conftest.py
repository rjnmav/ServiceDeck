"""Pytest shared fixtures, mocks, and test configuration."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    PermissionDeniedError,
    ServiceNotFoundError,
    ServiceOperationError,
)
from servicedeck.backend.models.service import (
    Service,
    ServiceResourceUsage,
    normalize_service_name,
    validate_scope,
)


class FakeSystemdAdapter:
    """In-memory fake implementation of SystemdAdapter supporting user and system scopes."""

    def __init__(self, services: list[Service] | None = None) -> None:
        self.healthy_scopes: dict[str, bool] = {"user": True, "system": True}
        self.denied_operations: set[tuple[str, str]] = set()  # (action, scope)
        self.failing_operations: set[tuple[str, str]] = set()  # (operation, scope)
        self.calls: list[tuple[str, str, str]] = []  # (method, name, scope)
        self.unit_files: dict[tuple[str, str], tuple[str | None, str]] = {}
        self.service_logs: dict[tuple[str, str], str] = {}
        self.service_resources: dict[tuple[str, str], ServiceResourceUsage] = {}

        initial = services or [
            # User scope services
            Service(
                name="plasma-runner.service",
                description="Plasma desktop runner",
                load_state="loaded",
                active_state="active",
                sub_state="running",
                unit_file_state="enabled",
                scope="user",
            ),
            Service(
                name="pipewire.service",
                description="PipeWire Multimedia Service",
                load_state="loaded",
                active_state="active",
                sub_state="running",
                unit_file_state="enabled",
                scope="user",
            ),
            Service(
                name="user-test.service",
                description="User test service",
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
                unit_file_state="disabled",
                scope="user",
            ),
            # System scope services
            Service(
                name="ssh.service",
                description="OpenBSD Secure Shell server",
                load_state="loaded",
                active_state="active",
                sub_state="running",
                unit_file_state="enabled",
                scope="system",
            ),
            Service(
                name="nginx.service",
                description="A high performance web server",
                load_state="loaded",
                active_state="inactive",
                sub_state="dead",
                unit_file_state="disabled",
                scope="system",
            ),
            Service(
                name="broken.service",
                description="A broken test service",
                load_state="loaded",
                active_state="failed",
                sub_state="failed",
                unit_file_state="enabled",
                scope="system",
            ),
        ]
        self._services: dict[tuple[str, str], Service] = {(s.scope, s.name): s for s in initial}

    async def is_healthy(self, scope: str = "user") -> bool:
        valid_scope = validate_scope(scope)
        return self.healthy_scopes.get(valid_scope, True)

    async def list_services(self, scope: str = "user") -> list[Service]:
        valid_scope = validate_scope(scope)
        self.calls.append(("list_services", "*", valid_scope))
        matching = [s for (s_scope, _), s in self._services.items() if s_scope == valid_scope]
        return sorted(matching, key=lambda s: s.name)

    async def get_service(self, name: str, scope: str = "user") -> Service:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("get_service", clean, valid_scope))
        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)
        return self._services[key]

    async def start_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("start_service", clean, valid_scope))

        if ("start", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="start", service_name=clean)
        if ("start", valid_scope) in self.failing_operations:
            raise ServiceOperationError(
                service_name=clean, operation="start", reason="Unit failed to start"
            )

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state="active",
            sub_state="running",
            unit_file_state=prev.unit_file_state,
            scope=valid_scope,
        )

    async def stop_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("stop_service", clean, valid_scope))

        if ("stop", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="stop", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state="inactive",
            sub_state="dead",
            unit_file_state=prev.unit_file_state,
            scope=valid_scope,
        )

    async def restart_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("restart_service", clean, valid_scope))

        if ("restart", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="restart", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state="active",
            sub_state="running",
            unit_file_state=prev.unit_file_state,
            scope=valid_scope,
        )

    async def reload_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("reload_service", clean, valid_scope))

        if ("reload", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="reload", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

    async def enable_service(self, name: str, scope: str = "user") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("enable_service", clean, valid_scope))

        if ("enable", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="enable", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state=prev.active_state,
            sub_state=prev.sub_state,
            unit_file_state="enabled",
            scope=valid_scope,
        )

    async def disable_service(self, name: str, scope: str = "user") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("disable_service", clean, valid_scope))

        if ("disable", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="disable", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state=prev.active_state,
            sub_state=prev.sub_state,
            unit_file_state="disabled",
            scope=valid_scope,
        )

    async def mask_service(self, name: str, scope: str = "user") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("mask_service", clean, valid_scope))

        if ("mask", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="mask", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state="inactive",
            sub_state="dead",
            unit_file_state="masked",
            scope=valid_scope,
        )

    async def unmask_service(self, name: str, scope: str = "user") -> None:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("unmask_service", clean, valid_scope))

        if ("unmask", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="unmask", service_name=clean)

        key = (valid_scope, clean)
        if key not in self._services:
            raise ServiceNotFoundError(clean)

        prev = self._services[key]
        self._services[key] = Service(
            name=prev.name,
            description=prev.description,
            load_state=prev.load_state,
            active_state=prev.active_state,
            sub_state=prev.sub_state,
            unit_file_state="disabled",
            scope=valid_scope,
        )

    async def reload_daemon(self, scope: str = "user") -> None:
        valid_scope = validate_scope(scope)
        self.calls.append(("reload_daemon", "*", valid_scope))

        if ("reload_daemon", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="reload_daemon", service_name="*")

    async def get_unit_file(self, name: str, scope: str = "user") -> tuple[str | None, str]:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("get_unit_file", clean, valid_scope))

        key = (valid_scope, clean)
        if key in self.unit_files:
            return self.unit_files[key]

        if key not in self._services:
            raise ServiceNotFoundError(clean)

        path = (
            f"/etc/systemd/system/{clean}"
            if valid_scope == "system"
            else f"/home/user/.config/systemd/user/{clean}"
        )
        content = f"[Unit]\nDescription={self._services[key].description}\n\n[Service]\nExecStart=/usr/bin/python3 -m {clean}\n"
        return path, content

    async def get_service_resources(self, name: str, scope: str = "user") -> ServiceResourceUsage:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("get_service_resources", clean, valid_scope))

        key = (valid_scope, clean)
        if key in self.service_resources:
            return self.service_resources[key]

        if key not in self._services:
            raise ServiceNotFoundError(clean)

        return ServiceResourceUsage(
            service=clean,
            scope=valid_scope,
            is_active=(self._services[key].active_state == "active"),
            cpu_usage_nsec=1_500_000_000,
            memory_current=104_857_600,
            io_read_bytes=10240,
            io_write_bytes=20480,
            tasks_current=4,
            process_count=1,
            active_enter_timestamp_usec=1710000000000000,
            main_pid=1234,
        )

    async def get_service_logs(self, name: str, lines: int = 200, scope: str = "user") -> str:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("get_service_logs", clean, valid_scope))

        key = (valid_scope, clean)
        if key in self.service_logs:
            return self.service_logs[key]

        if key not in self._services:
            raise ServiceNotFoundError(clean)

        return f"Mar 22 10:00:00 test-host {clean}[1234]: Started {clean}.\nMar 22 10:00:01 test-host {clean}[1234]: Service is running smoothly.\n"

    async def create_service(
        self, name: str, content: str, scope: str = "user", overwrite: bool = False
    ) -> str:
        valid_scope = validate_scope(scope)
        clean = normalize_service_name(name)
        self.calls.append(("create_service", clean, valid_scope))

        if ("create", valid_scope) in self.denied_operations:
            raise PermissionDeniedError(action="create", service_name=clean)

        key = (valid_scope, clean)
        if not overwrite and key in self._services:
            raise ServiceOperationError(
                service_name=clean, operation="create", reason=f"Unit '{clean}' already exists."
            )

        path = (
            f"/home/user/.config/systemd/user/{clean}"
            if valid_scope == "user"
            else f"/etc/systemd/system/{clean}"
        )
        self.unit_files[key] = (path, content)
        self._services[key] = Service(
            name=clean,
            description=clean,
            load_state="loaded",
            active_state="inactive",
            sub_state="dead",
            unit_file_state="disabled",
            scope=valid_scope,
        )
        return path


@pytest.fixture
def fake_adapter() -> FakeSystemdAdapter:
    """Fixture providing a controllable in-memory fake SystemdAdapter."""
    return FakeSystemdAdapter()


@pytest.fixture
def service_manager(fake_adapter: FakeSystemdAdapter) -> ServiceManager:
    """Fixture providing a ServiceManager backed by the fake adapter with default scope 'user'."""
    return ServiceManager(adapter=fake_adapter, default_scope="user")


@pytest.fixture
def test_settings() -> Settings:
    """Fixture providing test configuration settings."""
    return Settings(
        host="127.0.0.1",
        port=8000,
        log_level="DEBUG",
        debug=True,
    )


@pytest.fixture
def app(service_manager: ServiceManager, test_settings: Settings) -> Any:
    """Fixture providing a FastAPI application configured with fake ServiceManager."""
    return create_app(settings=test_settings, service_manager=service_manager)


@pytest.fixture
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """Async HTTP client fixture communicating with the test application."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
