"""Unit tests for the Service domain model and normalization."""

import pytest

from servicedeck.backend.exceptions import InvalidServiceNameError, ServiceDeckError
from servicedeck.backend.models.service import (
    Service,
    normalize_service_name,
    validate_scope,
)


def test_service_model_creation() -> None:
    svc = Service(
        name="plasma-runner.service",
        description="Plasma runner",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
        scope="user",
    )
    assert svc.name == "plasma-runner.service"
    assert svc.description == "Plasma runner"
    assert svc.load_state == "loaded"
    assert svc.active_state == "active"
    assert svc.sub_state == "running"
    assert svc.unit_file_state == "enabled"
    assert svc.scope == "user"
    assert svc.is_active is True
    assert svc.is_running is True
    assert svc.is_failed is False
    assert svc.is_enabled is True


def test_service_model_default_scope() -> None:
    svc = Service(
        name="test.service",
        description="test",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
    )
    assert svc.scope == "user"


def test_validate_scope() -> None:
    assert validate_scope("user") == "user"
    assert validate_scope("system") == "system"
    assert validate_scope("  USER  ") == "user"
    assert validate_scope(" SYSTEM ") == "system"

    with pytest.raises(ServiceDeckError):
        validate_scope("invalid")

    with pytest.raises(ServiceDeckError):
        validate_scope("")


def test_service_model_failed_state() -> None:
    svc = Service(
        name="broken.service",
        description="Broken test service",
        load_state="loaded",
        active_state="failed",
        sub_state="failed",
        unit_file_state="disabled",
        scope="system",
    )
    assert svc.is_active is False
    assert svc.is_running is False
    assert svc.is_failed is True
    assert svc.is_enabled is False
    assert svc.scope == "system"


def test_service_model_immutability() -> None:
    svc = Service(
        name="ssh.service",
        description="SSH server",
        load_state="loaded",
        active_state="active",
        sub_state="running",
        unit_file_state="enabled",
        scope="system",
    )
    with pytest.raises(AttributeError):
        svc.name = "other.service"  # type: ignore[misc]


def test_normalize_service_name_valid() -> None:
    assert normalize_service_name("ssh") == "ssh.service"
    assert normalize_service_name("ssh.service") == "ssh.service"
    assert normalize_service_name("user@1000.service") == "user@1000.service"
    assert normalize_service_name("  nginx  ") == "nginx.service"


def test_normalize_service_name_invalid() -> None:
    with pytest.raises(InvalidServiceNameError):
        normalize_service_name("")

    with pytest.raises(InvalidServiceNameError):
        normalize_service_name("   ")

    with pytest.raises(InvalidServiceNameError):
        normalize_service_name("ssh; rm -rf /")

    with pytest.raises(InvalidServiceNameError):
        normalize_service_name("svc$name")
