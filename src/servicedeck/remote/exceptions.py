"""Protocol-level exceptions for the ServiceDeck remote management layer."""

from typing import Any

from servicedeck.backend.exceptions import (
    RemoteConnectionError,
    RemoteHostKeyChangedError,
    ServiceDeckError,
    SSHAuthenticationError,
)


class RemoteProtocolError(ServiceDeckError):
    """Raised for protocol framing, decoding, or serialization errors."""

    def __init__(self, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message, details or {})


class RemoteTimeoutError(ServiceDeckError):
    """Raised when a remote protocol request times out waiting for a response."""

    def __init__(self, request_id: int, method: str, timeout_seconds: float) -> None:
        super().__init__(
            f"Request {request_id} ('{method}') timed out after {timeout_seconds:.1f}s",
            details={
                "request_id": request_id,
                "method": method,
                "timeout_seconds": timeout_seconds,
            },
        )
        self.request_id = request_id
        self.method = method
        self.timeout_seconds = timeout_seconds


class UnknownMethodError(ServiceDeckError):
    """Raised when an unknown remote protocol method is requested."""

    def __init__(self, method: str) -> None:
        super().__init__(
            f"Unknown protocol method '{method}'",
            details={"method": method},
        )
        self.method = method


__all__ = [
    "RemoteConnectionError",
    "RemoteHostKeyChangedError",
    "RemoteProtocolError",
    "RemoteTimeoutError",
    "SSHAuthenticationError",
    "ServiceDeckError",
    "UnknownMethodError",
]
