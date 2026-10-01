"""Unit tests for API client auth exception mapping."""

import httpx
import pytest

from servicedeck.api_client.exceptions import (
    PolkitAgentUnavailableError,
    ServiceAuthenticationRequiredError,
    ServiceAuthorizationDeniedError,
    ServiceDeckHTTPError,
    ServicePermissionDeniedError,
)
from servicedeck.api_client.transport import _raise_for_status


def test_401_maps_to_service_authentication_required() -> None:
    """HTTP 401 response raises ServiceAuthenticationRequiredError."""
    req = httpx.Request("GET", "http://127.0.0.1:8000/api/services")
    resp = httpx.Response(
        401,
        request=req,
        json={
            "error": "AuthenticationRequired",
            "message": "Authentication required.",
            "details": {},
        },
    )

    with pytest.raises(ServiceAuthenticationRequiredError) as exc_info:
        _raise_for_status(resp)

    err = exc_info.value
    assert err.status_code == 401
    assert err.error_type == "AuthenticationRequired"
    assert issubclass(ServiceAuthenticationRequiredError, ServiceDeckHTTPError)


def test_403_polkit_agent_unavailable_mapping() -> None:
    """HTTP 403 with PolkitAgentUnavailable error type maps to PolkitAgentUnavailableError."""
    req = httpx.Request("POST", "http://127.0.0.1:8000/api/services/nginx.service/restart")
    resp = httpx.Response(
        403,
        request=req,
        json={
            "error": "PolkitAgentUnavailable",
            "message": "No Polkit authentication agent available.",
            "details": {"action": "restart", "service": "nginx.service"},
        },
    )

    with pytest.raises(PolkitAgentUnavailableError) as exc_info:
        _raise_for_status(resp)

    err = exc_info.value
    assert err.status_code == 403
    assert err.error_type == "PolkitAgentUnavailable"
    assert issubclass(PolkitAgentUnavailableError, ServicePermissionDeniedError)


def test_403_authorization_denied_mapping() -> None:
    """HTTP 403 with AuthorizationDenied error type maps to ServiceAuthorizationDeniedError."""
    req = httpx.Request("POST", "http://127.0.0.1:8000/api/services/sshd.service/stop")
    resp = httpx.Response(
        403,
        request=req,
        json={
            "error": "AuthorizationDenied",
            "message": "Authorization denied by Polkit policy.",
            "details": {"action": "stop", "service": "sshd.service"},
        },
    )

    with pytest.raises(ServiceAuthorizationDeniedError) as exc_info:
        _raise_for_status(resp)

    err = exc_info.value
    assert err.status_code == 403
    assert err.error_type == "AuthorizationDenied"
    assert issubclass(ServiceAuthorizationDeniedError, ServicePermissionDeniedError)


def test_403_generic_permission_denied_mapping() -> None:
    """HTTP 403 with generic error type maps to ServicePermissionDeniedError."""
    req = httpx.Request("POST", "http://127.0.0.1:8000/api/services/app.service/start")
    resp = httpx.Response(
        403,
        request=req,
        json={"error": "PermissionDeniedError", "message": "Permission denied.", "details": {}},
    )

    with pytest.raises(ServicePermissionDeniedError) as exc_info:
        _raise_for_status(resp)

    err = exc_info.value
    assert err.status_code == 403
    assert err.error_type == "PermissionDeniedError"
