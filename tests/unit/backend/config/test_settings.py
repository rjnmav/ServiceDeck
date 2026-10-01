"""Unit tests for backend configuration and settings."""

import os
from unittest import mock

from servicedeck.backend.config.settings import Settings


def test_settings_defaults() -> None:
    settings = Settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.log_level == "INFO"
    assert settings.debug is False
    assert settings.dbus_address is None
    assert settings.systemd_bus_name == "org.freedesktop.systemd1"
    assert settings.systemd_object_path == "/org/freedesktop/systemd1"
    assert settings.allow_interactive_authorization is True


def test_settings_env_override() -> None:
    env = {
        "SERVICEDECK_HOST": "0.0.0.0",
        "SERVICEDECK_PORT": "9090",
        "SERVICEDECK_LOG_LEVEL": "DEBUG",
        "SERVICEDECK_DEBUG": "true",
    }
    with mock.patch.dict(os.environ, env):
        settings = Settings()
        assert settings.host == "0.0.0.0"
        assert settings.port == 9090
        assert settings.log_level == "DEBUG"
        assert settings.debug is True
