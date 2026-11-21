"""Pydantic schemas for remote device and service management API endpoints."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr

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


class HostKeyResponse(BaseModel):
    """The SSH host key a remote server presents and whether it is trusted."""

    model_config = ConfigDict(frozen=True)

    hostname: str
    port: int
    status: Literal["trusted", "unknown", "changed"]
    key_type: str
    fingerprint: str = Field(..., description="SHA256 fingerprint, as shown by ssh-keygen -l")


class TrustHostKeyRequest(BaseModel):
    """Confirmation of the fingerprint the user verified."""

    model_config = ConfigDict(frozen=True)

    fingerprint: str = Field(..., min_length=1, description="Fingerprint the user confirmed")


class SetupKeyRequest(BaseModel):
    """One-time remote account password used to install the SSH login key."""

    model_config = ConfigDict(frozen=True)

    password: SecretStr = Field(
        ...,
        description="Remote account password. Used for a single SSH login to install the key; "
        "never stored or logged.",
    )


class SetupKeyResponse(BaseModel):
    """Result of installing the SSH login key on a remote device."""

    model_config = ConfigDict(frozen=True)

    device: RemoteDeviceResponse
    key_path: str
    key_fingerprint: str
    added: bool = Field(..., description="False if the key was already authorized")


__all__ = [
    "HostKeyResponse",
    "RemoteConnectionResponse",
    "RemoteDeviceCreateRequest",
    "RemoteDeviceDisconnectResponse",
    "RemoteDeviceResponse",
    "SetupKeyRequest",
    "SetupKeyResponse",
    "TrustHostKeyRequest",
]
