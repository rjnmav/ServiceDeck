"""HTTP transport layer for the ServiceDeck API client."""

from typing import Any

import httpx

from servicedeck.api_client.exceptions import (
    BackendUnavailableError,
    InvalidServiceNameError,
    PolkitAgentUnavailableError,
    ServiceAuthenticationRequiredError,
    ServiceAuthorizationDeniedError,
    ServiceDeckConnectionError,
    ServiceDeckHTTPError,
    ServiceNotFoundError,
    ServiceOperationError,
    ServicePermissionDeniedError,
)

DEFAULT_TIMEOUT = 10.0


def _parse_error_payload(response: httpx.Response) -> tuple[str, str, dict[str, Any]]:
    """Extract (error_type, message, details) from an error response."""
    try:
        data = response.json()
        if isinstance(data, dict):
            error_type = data.get("error", "HTTP_ERROR")
            message = data.get("message") or data.get("detail") or response.text or "HTTP Error"
            details = data.get("details", {})
            return error_type, message, details
    except Exception:
        pass
    return "HTTP_ERROR", response.text or f"HTTP {response.status_code}", {}


def _raise_for_status(response: httpx.Response) -> None:
    """Map HTTP error status codes to typed ServiceDeck exceptions."""
    if response.is_success:
        return

    status_code = response.status_code
    error_type, message, details = _parse_error_payload(response)

    if status_code == 401:
        raise ServiceAuthenticationRequiredError(status_code, message, error_type, details)
    if status_code == 404:
        raise ServiceNotFoundError(status_code, message, error_type, details)
    if status_code == 403:
        if error_type == "PolkitAgentUnavailable":
            raise PolkitAgentUnavailableError(status_code, message, error_type, details)
        if error_type == "AuthorizationDenied":
            raise ServiceAuthorizationDeniedError(status_code, message, error_type, details)
        raise ServicePermissionDeniedError(status_code, message, error_type, details)
    if status_code == 400:
        if error_type == "INVALID_SERVICE_NAME":
            raise InvalidServiceNameError(status_code, message, error_type, details)
        raise ServiceOperationError(status_code, message, error_type, details)
    if status_code == 503:
        raise BackendUnavailableError(status_code, message, error_type, details)

    raise ServiceDeckHTTPError(status_code, message, error_type, details)


class SyncTransport:
    """Synchronous HTTP transport using httpx.Client."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Send a synchronous HTTP request, returning parsed JSON."""
        clean_path = "/" + path.lstrip("/")
        try:
            response = self._client.request(
                method=method,
                url=clean_path,
                params=params,
                json=json,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ServiceDeckConnectionError(
                f"Failed to connect to ServiceDeck backend at {self.base_url}: {exc}"
            ) from exc

        _raise_for_status(response)
        if response.content:
            return response.json()
        return None

    def close(self) -> None:
        """Close the underlying HTTP client."""
        self._client.close()

    def __enter__(self) -> "SyncTransport":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


class AsyncTransport:
    """Asynchronous HTTP transport using httpx.AsyncClient."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8000",
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=timeout,
            headers={"Accept": "application/json"},
        )

    async def request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
        json: Any = None,
    ) -> Any:
        """Send an asynchronous HTTP request, returning parsed JSON."""
        clean_path = "/" + path.lstrip("/")
        try:
            response = await self._client.request(
                method=method,
                url=clean_path,
                params=params,
                json=json,
            )
        except (httpx.ConnectError, httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ServiceDeckConnectionError(
                f"Failed to connect to ServiceDeck backend at {self.base_url}: {exc}"
            ) from exc

        _raise_for_status(response)
        if response.content:
            return response.json()
        return None

    async def aclose(self) -> None:
        """Close the underlying HTTP async client."""
        await self._client.aclose()

    async def __aenter__(self) -> "AsyncTransport":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.aclose()
