"""Unit tests for FastAPI security exception handlers and startup warnings."""

import logging
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from tests.conftest import FakeSystemdAdapter

from servicedeck.backend.app.application import create_app
from servicedeck.backend.config.settings import Settings
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    AuthorizationDeniedError,
    PolkitAgentUnavailableError,
)


class MockAuthAdapter(FakeSystemdAdapter):
    """Adapter that raises specific security exceptions."""

    def __init__(self, exc_to_raise: Exception) -> None:
        super().__init__()
        self.exc_to_raise = exc_to_raise

    async def start_service(self, name: str, scope: str = "user", mode: str = "replace") -> None:
        raise self.exc_to_raise


@pytest.mark.asyncio
async def test_polkit_agent_unavailable_handler() -> None:
    """PolkitAgentUnavailableError returns HTTP 403 with error='PolkitAgentUnavailable'."""
    exc = PolkitAgentUnavailableError(
        action="restart", service_name="nginx.service", scope="system"
    )
    adapter = MockAuthAdapter(exc)
    manager = ServiceManager(adapter=adapter)
    app = create_app(settings=Settings(), service_manager=manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/services/nginx/start?scope=system")

    assert resp.status_code == 403
    data = resp.json()
    assert data["error"] == "PolkitAgentUnavailable"
    assert "no Polkit authentication agent is available" in data["message"]
    assert data["details"]["scope"] == "system"


@pytest.mark.asyncio
async def test_authorization_denied_handler() -> None:
    """AuthorizationDeniedError returns HTTP 403 with error='AuthorizationDenied'."""
    exc = AuthorizationDeniedError(
        action="stop",
        service_name="sshd.service",
        reason="Polkit policy denied operation",
    )
    adapter = MockAuthAdapter(exc)
    manager = ServiceManager(adapter=adapter)
    app = create_app(settings=Settings(), service_manager=manager)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/api/services/sshd/start?scope=system")

    assert resp.status_code == 403
    data = resp.json()
    assert data["error"] == "AuthorizationDenied"
    assert "Permission denied" in data["message"]


@pytest.mark.asyncio
async def test_startup_security_warnings(caplog: pytest.LogCaptureFixture) -> None:
    """Lifespan emits security warnings when host is non-loopback or started as root."""
    settings = Settings(host="0.0.0.0")
    adapter = FakeSystemdAdapter()
    manager = ServiceManager(adapter=adapter)

    with caplog.at_level(logging.WARNING):
        with patch("os.getuid", return_value=0, create=True):
            app = create_app(settings=settings, service_manager=manager)
            async with app.router.lifespan_context(app):
                pass

    messages = [rec.message for rec in caplog.records]
    assert any("Binding to non-loopback addresses" in msg for msg in messages)
    assert any("running as root (UID 0)" in msg for msg in messages)
