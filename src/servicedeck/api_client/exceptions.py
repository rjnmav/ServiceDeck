"""Exceptions raised by the ServiceDeck API client."""

from typing import Any


class ServiceDeckAPIError(Exception):
    """Base exception for all ServiceDeck API client errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def __str__(self) -> str:
        return self.message


class ServiceDeckConnectionError(ServiceDeckAPIError):
    """Raised when communication with the ServiceDeck backend fails (network/timeout)."""


class ServiceDeckHTTPError(ServiceDeckAPIError):
    """Raised when the ServiceDeck backend returns an HTTP error status code."""

    def __init__(
        self,
        status_code: int,
        message: str,
        error_type: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message, details)
        self.status_code = status_code
        self.error_type = error_type or "HTTP_ERROR"

    def __str__(self) -> str:
        return f"[{self.status_code}] {self.error_type}: {self.message}"


class ServiceNotFoundError(ServiceDeckHTTPError):
    """Raised when a requested service unit is not found (HTTP 404)."""


class ServiceAuthenticationRequiredError(ServiceDeckHTTPError):
    """Raised when authentication is required (HTTP 401)."""


class ServicePermissionDeniedError(ServiceDeckHTTPError):
    """Raised when an operation is forbidden / permission denied (HTTP 403)."""


class ServiceAuthorizationDeniedError(ServicePermissionDeniedError):
    """Raised when an operation is denied by Polkit or system authorization policy (HTTP 403)."""


class PolkitAgentUnavailableError(ServicePermissionDeniedError):
    """Raised when Polkit requires interactive authentication but no agent is available (HTTP 403)."""


class InvalidServiceNameError(ServiceDeckHTTPError):
    """Raised when an invalid service name is provided (HTTP 400)."""


class ServiceOperationError(ServiceDeckHTTPError):
    """Raised when a systemd service operation fails (HTTP 400)."""


class BackendUnavailableError(ServiceDeckHTTPError):
    """Raised when the backend or systemd D-Bus connection is unavailable (HTTP 503)."""


# Remote connection and authorization exceptions (for Phase 2 remote management)
class RemoteConnectionError(ServiceDeckAPIError):
    """Base exception for remote SSH or transport connection failures."""


class RemoteHostKeyChangedError(RemoteConnectionError):
    """Raised when the remote SSH host key does not match known_hosts."""


class SSHAuthenticationError(RemoteConnectionError):
    """Raised when SSH authentication fails."""


class RemoteDeviceNotTrustedError(ServiceDeckAPIError):
    """Raised when operating on a remote device that is not trusted/paired."""


class RemoteDeviceRevokedError(ServiceDeckAPIError):
    """Raised when operating on a remote device whose authorization has been revoked."""


class RemoteAuthorizationMissingError(ServiceDeckAPIError):
    """Raised when the remote identity lacks systemd management authorization."""
