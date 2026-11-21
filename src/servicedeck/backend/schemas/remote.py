"""Pydantic schemas for remote device and service management API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

AgentMode = Literal["bundled", "installed", "auto"]


class RemoteDeviceCreateRequest(BaseModel):
    """Payload to register a new remote device for SSH management."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(..., description="Unique machine identifier (slug or host alias)")
    display_name: str = Field(..., description="Human-readable device title")
    hostname: str = Field(..., description="Remote IP address or fully qualified domain name")
    port: int = Field(default=22, ge=1, le=65535, description="SSH port")
    username: str | None = Field(default=None, description="SSH login username")
    ssh_key_path: str | None = Field(default=None, description="Path to private SSH key file")
    agent_mode: AgentMode = Field(
        default="bundled",
        description="How the remote agent is started: 'bundled' streams it over SSH (no remote "
        "install), 'installed' runs servicedeck-remote, 'auto' prefers an installed agent.",
    )


class RemoteDeviceResponse(BaseModel):
    """Device description including live SSH connection status."""

    model_config = ConfigDict(frozen=True)

    id: str
    display_name: str
    hostname: str
    port: int
    username: str | None
    ssh_key_path: str | None
    agent_mode: AgentMode = "bundled"
    connected: bool


class RemoteConnectionResponse(BaseModel):
    """Connection status and remote agent handshake metadata."""

    model_config = ConfigDict(frozen=True)

    device_id: str
    connected: bool
    remote_host: str | None = None
    remote_user: str | None = None
    remote_uid: int | None = None
    remote_version: str | None = None


class RemoteDeviceDisconnectResponse(BaseModel):
    """Result of an explicit device disconnect command."""

    model_config = ConfigDict(frozen=True)

    device_id: str
    connected: bool = False


__all__ = [
    "RemoteConnectionResponse",
    "RemoteDeviceCreateRequest",
    "RemoteDeviceDisconnectResponse",
    "RemoteDeviceResponse",
]
