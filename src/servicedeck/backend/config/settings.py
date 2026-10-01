"""Central configuration for ServiceDeck backend."""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment or defaults."""

    model_config = SettingsConfigDict(
        env_prefix="SERVICEDECK_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # API Server Configuration
    host: str = Field(
        default="127.0.0.1",
        description="Host address for FastAPI server. Defaults to 127.0.0.1 (loopback) to prevent "
        "unauthenticated network exposure. Remote access is achieved via SSH tunnels.",
    )
    port: int = Field(default=8000, description="Port for FastAPI server")
    debug: bool = Field(default=False, description="Enable debug mode and auto-reload")
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARN, ERROR)")

    # Metadata
    app_name: str = Field(default="ServiceDeck Backend", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application version")

    # D-Bus & systemd Configuration
    dbus_address: str | None = Field(
        default=None,
        description="Explicit D-Bus bus address (defaults to system bus if None)",
    )
    systemd_bus_name: str = Field(
        default="org.freedesktop.systemd1",
        description="D-Bus well-known name for systemd",
    )
    systemd_object_path: str = Field(
        default="/org/freedesktop/systemd1",
        description="Root D-Bus object path for systemd Manager",
    )
    allow_interactive_authorization: bool = Field(
        default=True,
        description="Whether to pass ALLOW_INTERACTIVE_AUTHORIZATION on D-Bus calls, allowing "
        "desktop Polkit agents to prompt for authentication when required.",
    )


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached Settings singleton."""
    return Settings()
