"""Protocol message dataclasses for the ServiceDeck remote protocol."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PROTOCOL_VERSION = 1


@dataclass(slots=True)
class ErrorDetail:
    """Error information within a response message."""

    code: str = ""
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class HelloMessage:
    """Startup handshake message sent by the remote agent to the client."""

    type: Literal["hello"] = "hello"
    version: int = PROTOCOL_VERSION
    host: str = ""
    user: str = ""
    uid: int = -1
    servicedeck_version: str = ""


@dataclass(frozen=True, slots=True)
class RequestMessage:
    """Request message sent from the local client to the remote agent."""

    type: Literal["request"] = "request"
    id: int = 0
    method: str = ""
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ResponseMessage:
    """Response message sent from the remote agent to the local client."""

    type: Literal["response"] = "response"
    id: int = 0
    success: bool = True
    result: Any = None
    error: ErrorDetail | None = None


@dataclass(frozen=True, slots=True)
class AuthChallengeMessage:
    """Authentication challenge message sent from remote agent when Polkit/PAM requires input."""

    type: Literal["auth_challenge"] = "auth_challenge"
    id: int = 0
    challenge: str = ""
    prompt: str = ""
    echo: bool = False


@dataclass(frozen=True, slots=True)
class AuthResponseMessage:
    """Authentication response message sent from client supplying challenged credentials."""

    type: Literal["auth_response"] = "auth_response"
    id: int = 0
    response: str = ""


@dataclass(frozen=True, slots=True)
class GoodbyeMessage:
    """Graceful connection termination notification."""

    type: Literal["goodbye"] = "goodbye"
    reason: str = "shutdown"


ProtocolMessage = (
    HelloMessage
    | RequestMessage
    | ResponseMessage
    | AuthChallengeMessage
    | AuthResponseMessage
    | GoodbyeMessage
)


def success_response(request_id: int, result: Any = None) -> ResponseMessage:
    """Construct a successful ResponseMessage with the given result payload."""
    return ResponseMessage(id=request_id, success=True, result=result)


def error_response(
    request_id: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> ResponseMessage:
    """Construct an error ResponseMessage with structured ErrorDetail."""
    return ResponseMessage(
        id=request_id,
        success=False,
        error=ErrorDetail(code=code, message=message, details=details or {}),
    )


__all__ = [
    "PROTOCOL_VERSION",
    "AuthChallengeMessage",
    "AuthResponseMessage",
    "ErrorDetail",
    "GoodbyeMessage",
    "HelloMessage",
    "ProtocolMessage",
    "RequestMessage",
    "ResponseMessage",
    "error_response",
    "success_response",
]
