"""Domain and application exceptions for ServiceDeck backend."""


class ServiceDeckError(Exception):
    """Base exception for all ServiceDeck backend errors."""

    def __init__(self, message: str, details: dict | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}


class SystemdConnectionError(ServiceDeckError):
    """Raised when connecting or communicating with the system D-Bus/systemd fails."""


class ServiceNotFoundError(ServiceDeckError):
    """Raised when a specified systemd service unit is not found."""

    def __init__(self, service_name: str, message: str | None = None) -> None:
        msg = message or f"Service unit '{service_name}' not found."
        super().__init__(msg, details={"service_name": service_name})
        self.service_name = service_name


class InvalidServiceNameError(ServiceDeckError):
    """Raised when a service name is malformed or invalid."""

    def __init__(self, service_name: str, reason: str | None = None) -> None:
        msg = f"Invalid service unit name '{service_name}'"
        if reason:
            msg += f": {reason}"
        super().__init__(msg, details={"service_name": service_name, "reason": reason})
        self.service_name = service_name


class PermissionDeniedError(ServiceDeckError):
    """Raised when an operation is denied due to lack of permissions or Polkit authorization."""

    def __init__(
        self,
        action: str,
        service_name: str | None = None,
        reason: str | None = None,
    ) -> None:
        msg = f"Permission denied for operation '{action}'"
        if service_name:
            msg += f" on service '{service_name}'"
        if reason:
            msg += f" ({reason})"
        super().__init__(
            msg,
            details={"action": action, "service_name": service_name, "reason": reason},
        )
        self.action = action
        self.service_name = service_name


class AuthorizationDeniedError(PermissionDeniedError):
    """Raised when an operation is denied by Polkit or system authorization policy."""


class PolkitAgentUnavailableError(PermissionDeniedError):
    """Raised when Polkit requires interactive authentication but no agent is available."""

    def __init__(
        self,
        action: str,
        service_name: str | None = None,
        scope: str = "user",
        message: str | None = None,
    ) -> None:
        default_msg = (
            f"Interactive authorization required for '{action}' on '{service_name}' "
            f"({scope} scope), but no Polkit authentication agent is available. "
            f"If in a desktop session, verify your Polkit agent is running. "
            f"If in a headless or TUI session, configure system authorization."
        )
        msg = message or default_msg
        super().__init__(action=action, service_name=service_name, reason=msg)
        self.scope = scope
        self.details["scope"] = scope


class AuthenticationRequiredError(ServiceDeckError):
    """Raised when authentication is required to access an API or service resource."""

    def __init__(
        self, message: str = "Authentication required.", details: dict | None = None
    ) -> None:
        super().__init__(message, details=details)


# Remote connection and authorization exceptions (for Phase 2 remote management)
class RemoteConnectionError(ServiceDeckError):
    """Base exception for remote SSH or network connection failures."""


class RemoteHostKeyChangedError(RemoteConnectionError):
    """Raised when the remote SSH host key does not match known_hosts."""


class SSHAuthenticationError(RemoteConnectionError):
    """Raised when SSH authentication (public-key or agent) fails."""


class RemoteDeviceNotTrustedError(ServiceDeckError):
    """Raised when attempting to operate on a remote device that is not trusted/paired."""


class RemoteDeviceRevokedError(ServiceDeckError):
    """Raised when operating on a remote device whose authorization has been revoked."""


class RemoteAuthorizationMissingError(ServiceDeckError):
    """Raised when the authenticated remote identity lacks native systemd authorization."""


class ServiceOperationError(ServiceDeckError):
    """Raised when a service lifecycle operation (start/stop/restart/reload) fails."""

    def __init__(
        self,
        service_name: str,
        operation: str,
        reason: str | None = None,
    ) -> None:
        msg = f"Failed to {operation} service '{service_name}'"
        if reason:
            msg += f": {reason}"
        super().__init__(
            msg,
            details={"service_name": service_name, "operation": operation, "reason": reason},
        )
        self.service_name = service_name
        self.operation = operation
