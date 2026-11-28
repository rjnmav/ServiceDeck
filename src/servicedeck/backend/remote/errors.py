"""Turn an agent's error response back into the backend's domain exception.

Shared by every channel that talks to an agent: remote hosts (normal and root agent) and
the local root agent started for system unit file changes.
"""

from __future__ import annotations

from typing import Any

from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    InvalidServiceNameError,
    PermissionDeniedError,
    ServiceDeckError,
    ServiceNotFoundError,
    ServiceOperationError,
    SystemdConnectionError,
)
from servicedeck.remote.models import ResponseMessage

#: Agent error codes that, for a system-scope call by a normal user, mean "needs root".
ELEVATION_CODES = frozenset(
    {"AUTHENTICATION_REQUIRED", "AUTHORIZATION_DENIED", "PERMISSION_DENIED"}
)


def error_parts(response: ResponseMessage) -> tuple[str, str, dict[str, Any]]:
    """Return ``(code, message, details)`` of a failed response."""
    err = response.error
    code = err.code if err else "UNKNOWN"
    msg = err.message if err else "Remote operation failed"
    details = (err.details if err else None) or {}
    return code, msg, details


def exception_from_response(
    method: str, params: dict[str, Any] | None, response: ResponseMessage
) -> ServiceDeckError:
    """Build the domain exception a failed agent response describes."""
    code, msg, details = error_parts(response)
    name = str((params or {}).get("name", ""))

    if code == "SERVICE_NOT_FOUND":
        return ServiceNotFoundError(name, message=msg)
    if code == "INVALID_SERVICE_NAME":
        return InvalidServiceNameError(name, reason=msg)
    if code == "AUTHENTICATION_REQUIRED":
        return AuthenticationRequiredError(msg, details=details)
    if code == "AUTHORIZATION_DENIED":
        return AuthorizationDeniedError(action=method, service_name=name or None, reason=msg)
    if code == "PERMISSION_DENIED":
        return PermissionDeniedError(action=method, service_name=name or None, reason=msg)
    if code == "SERVICE_OPERATION_FAILED":
        return ServiceOperationError(service_name=name, operation=method, reason=msg)
    if code == "SYSTEMD_CONNECTION_ERROR":
        return SystemdConnectionError(msg)
    return ServiceDeckError(msg, details=details)


__all__ = ["ELEVATION_CODES", "error_parts", "exception_from_response"]
