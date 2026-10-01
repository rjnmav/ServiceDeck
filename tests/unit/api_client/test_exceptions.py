"""Tests for API client exception mappings and hierarchies."""

import httpx
import pytest

from servicedeck.api_client.exceptions import (
    BackendUnavailableError,
    InvalidServiceNameError,
    ServiceDeckAPIError,
    ServiceDeckConnectionError,
    ServiceDeckHTTPError,
    ServiceNotFoundError,
    ServiceOperationError,
    ServicePermissionDeniedError,
)
from servicedeck.api_client.transport import _raise_for_status


def test_exception_inheritance():
    """Verify all exceptions inherit from ServiceDeckAPIError."""
    assert issubclass(ServiceDeckConnectionError, ServiceDeckAPIError)
    assert issubclass(ServiceDeckHTTPError, ServiceDeckAPIError)
    assert issubclass(ServiceNotFoundError, ServiceDeckHTTPError)
    assert issubclass(ServicePermissionDeniedError, ServiceDeckHTTPError)
    assert issubclass(InvalidServiceNameError, ServiceDeckHTTPError)
    assert issubclass(ServiceOperationError, ServiceDeckHTTPError)
    assert issubclass(BackendUnavailableError, ServiceDeckHTTPError)


def test_raise_for_status_200():
    """Success response does not raise any exception."""
    resp = httpx.Response(200, json={"ok": True})
    _raise_for_status(resp)


def test_raise_for_status_404():
    """404 raises ServiceNotFoundError with message and details."""
    payload = {
        "error": "SERVICE_NOT_FOUND",
        "message": "Service 'unknown.service' not found",
        "details": {"service": "unknown.service"},
    }
    resp = httpx.Response(404, json=payload)
    with pytest.raises(ServiceNotFoundError) as exc_info:
        _raise_for_status(resp)

    err = exc_info.value
    assert err.status_code == 404
    assert err.error_type == "SERVICE_NOT_FOUND"
    assert "unknown.service" in err.message
    assert err.details == {"service": "unknown.service"}


def test_raise_for_status_403():
    """403 raises ServicePermissionDeniedError."""
    payload = {
        "error": "PERMISSION_DENIED",
        "message": "Polkit authorization failed",
        "details": {},
    }
    resp = httpx.Response(403, json=payload)
    with pytest.raises(ServicePermissionDeniedError) as exc_info:
        _raise_for_status(resp)

    assert exc_info.value.status_code == 403


def test_raise_for_status_400_invalid_name():
    """400 with INVALID_SERVICE_NAME raises InvalidServiceNameError."""
    payload = {
        "error": "INVALID_SERVICE_NAME",
        "message": "Invalid service unit name",
        "details": {"name": "invalid;;"},
    }
    resp = httpx.Response(400, json=payload)
    with pytest.raises(InvalidServiceNameError) as exc_info:
        _raise_for_status(resp)

    assert exc_info.value.status_code == 400


def test_raise_for_status_400_operation_error():
    """400 with any other error raises ServiceOperationError."""
    payload = {
        "error": "OPERATION_FAILED",
        "message": "Job failed to complete",
        "details": {},
    }
    resp = httpx.Response(400, json=payload)
    with pytest.raises(ServiceOperationError) as exc_info:
        _raise_for_status(resp)

    assert exc_info.value.status_code == 400


def test_raise_for_status_503():
    """503 raises BackendUnavailableError."""
    payload = {
        "error": "SYSTEMD_CONNECTION_ERROR",
        "message": "Cannot reach systemd daemon",
        "details": {},
    }
    resp = httpx.Response(503, json=payload)
    with pytest.raises(BackendUnavailableError) as exc_info:
        _raise_for_status(resp)

    assert exc_info.value.status_code == 503
