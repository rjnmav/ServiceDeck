"""Unit tests for ServiceDeck security exception hierarchy."""

from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    PermissionDeniedError,
    PolkitAgentUnavailableError,
    RemoteAuthorizationMissingError,
    RemoteConnectionError,
    RemoteDeviceNotTrustedError,
    RemoteDeviceRevokedError,
    RemoteHostKeyChangedError,
    ServiceDeckError,
    SSHAuthenticationError,
)


def test_permission_denied_inheritance() -> None:
    """AuthorizationDeniedError and PolkitAgentUnavailableError inherit from PermissionDeniedError."""
    assert issubclass(AuthorizationDeniedError, PermissionDeniedError)
    assert issubclass(PolkitAgentUnavailableError, PermissionDeniedError)
    assert issubclass(PermissionDeniedError, ServiceDeckError)


def test_polkit_agent_unavailable_details() -> None:
    """PolkitAgentUnavailableError carries structured action, service, and scope."""
    exc = PolkitAgentUnavailableError(
        action="restart", service_name="nginx.service", scope="system"
    )
    assert exc.action == "restart"
    assert exc.service_name == "nginx.service"
    assert exc.scope == "system"
    assert "no Polkit authentication agent is available" in exc.message
    assert exc.details["action"] == "restart"
    assert exc.details["service_name"] == "nginx.service"


def test_authentication_required_error() -> None:
    """AuthenticationRequiredError has default message and details."""
    exc = AuthenticationRequiredError()
    assert exc.message == "Authentication required."
    assert issubclass(AuthenticationRequiredError, ServiceDeckError)


def test_remote_exceptions_hierarchy() -> None:
    """Remote exception classes inherit from RemoteConnectionError or ServiceDeckError."""
    assert issubclass(RemoteConnectionError, ServiceDeckError)
    assert issubclass(RemoteHostKeyChangedError, RemoteConnectionError)
    assert issubclass(SSHAuthenticationError, RemoteConnectionError)
    assert issubclass(RemoteDeviceNotTrustedError, ServiceDeckError)
    assert issubclass(RemoteDeviceRevokedError, ServiceDeckError)
    assert issubclass(RemoteAuthorizationMissingError, ServiceDeckError)
