"""FastAPI application factory and lifecycle management."""

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from servicedeck.backend.api.router import api_router
from servicedeck.backend.config.settings import Settings, get_settings
from servicedeck.backend.core.remote_manager import RemoteManager
from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    InvalidServiceNameError,
    PermissionDeniedError,
    PolkitAgentUnavailableError,
    RemoteAuthorizationMissingError,
    RemoteConnectionError,
    RemoteDeviceNotTrustedError,
    RemoteDeviceRevokedError,
    RemoteHostKeyChangedError,
    ServiceDeckError,
    ServiceNotFoundError,
    ServiceOperationError,
    SSHAuthenticationError,
    SystemdConnectionError,
)
from servicedeck.backend.infrastructure.dbus.connection import DbusConnectionManager
from servicedeck.backend.infrastructure.dbus.systemd import DbusSystemdAdapter
from servicedeck.backend.schemas.service import ErrorDetail
from servicedeck.remote.exceptions import RemoteProtocolError, RemoteTimeoutError

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    service_manager: ServiceManager | None = None,
    remote_manager: RemoteManager | None = None,
) -> FastAPI:
    """Create and configure a new FastAPI application instance."""
    app_settings = settings or get_settings()

    connection_manager = DbusConnectionManager(app_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Manage application startup and shutdown lifecycle."""
        logger.info("Starting %s v%s", app_settings.app_name, app_settings.app_version)

        # Security checks on startup
        if app_settings.host not in ("127.0.0.1", "::1", "localhost"):
            logger.warning(
                "SECURITY WARNING: Backend is configured to bind to host '%s'. "
                "Binding to non-loopback addresses directly exposes unauthenticated API endpoints to the network. "
                "For remote management, bind to 127.0.0.1 and tunnel via SSH.",
                app_settings.host,
            )

        if hasattr(os, "getuid") and os.getuid() == 0:
            logger.warning(
                "SECURITY WARNING: ServiceDeck backend is running as root (UID 0). "
                "Running as root is strongly discouraged. ServiceDeck is designed to run as an unprivileged user "
                "with Polkit managing privilege escalation via D-Bus.",
            )

        # Initialize local ServiceManager
        if getattr(app.state, "service_manager", None) is None:
            if service_manager is not None:
                app.state.service_manager = service_manager
            else:
                try:
                    await connection_manager.connect("user")
                except Exception as exc:
                    logger.warning("Failed to connect to user D-Bus at startup: %s", exc)

                try:
                    await connection_manager.connect("system")
                except Exception as exc:
                    logger.warning("Failed to connect to system D-Bus at startup: %s", exc)

                adapter = DbusSystemdAdapter(
                    connection_manager=connection_manager,
                    settings=app_settings,
                )
                app.state.service_manager = ServiceManager(adapter=adapter, default_scope="user")
                logger.info(
                    "ServiceManager and D-Bus adapters initialized with default scope 'user'."
                )

        # Initialize RemoteManager
        if getattr(app.state, "remote_manager", None) is None:
            app.state.remote_manager = remote_manager or RemoteManager()
            logger.info("RemoteManager initialized on application state.")

        yield

        logger.info("Shutting down %s", app_settings.app_name)
        if hasattr(app.state, "remote_manager") and app.state.remote_manager is not None:
            await app.state.remote_manager.disconnect_all()
        await connection_manager.disconnect()

    app = FastAPI(
        title=app_settings.app_name,
        version=app_settings.app_version,
        description="REST API for Linux systemd service management and monitoring",
        lifespan=lifespan,
    )

    if service_manager is not None:
        app.state.service_manager = service_manager
    if remote_manager is not None:
        app.state.remote_manager = remote_manager

    # Register API routes
    app.include_router(api_router)

    @app.get(
        "/",
        summary="Root Overview",
        description="Root metadata endpoint providing links to docs, health, and services.",
    )
    async def root() -> dict[str, object]:
        return {
            "name": app_settings.app_name,
            "version": app_settings.app_version,
            "status": "running",
            "docs": "/docs",
            "redoc": "/redoc",
            "endpoints": {
                "health": "/api/health",
                "scope": "/api/scope",
                "services": "/api/services",
                "remote_devices": "/api/remote/devices",
            },
        }

    # Global Exception Handlers
    @app.exception_handler(ServiceNotFoundError)
    async def service_not_found_handler(
        request: Request, exc: ServiceNotFoundError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_404_NOT_FOUND,
            content=ErrorDetail(
                error="ServiceNotFoundError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(AuthenticationRequiredError)
    async def authentication_required_handler(
        request: Request, exc: AuthenticationRequiredError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            content=ErrorDetail(
                error="AuthenticationRequired",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(SSHAuthenticationError)
    async def ssh_authentication_handler(
        request: Request, exc: SSHAuthenticationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content=ErrorDetail(
                error="SSHAuthenticationError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteHostKeyChangedError)
    async def remote_host_key_handler(
        request: Request, exc: RemoteHostKeyChangedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=ErrorDetail(
                error="RemoteHostKeyChangedError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteTimeoutError)
    async def remote_timeout_handler(
        request: Request, exc: RemoteTimeoutError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            content=ErrorDetail(
                error="RemoteTimeoutError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteProtocolError)
    async def remote_protocol_handler(
        request: Request, exc: RemoteProtocolError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=ErrorDetail(
                error="RemoteProtocolError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteConnectionError)
    async def remote_connection_handler(
        request: Request, exc: RemoteConnectionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_502_BAD_GATEWAY,
            content=ErrorDetail(
                error="RemoteConnectionError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(PolkitAgentUnavailableError)
    async def polkit_agent_unavailable_handler(
        request: Request, exc: PolkitAgentUnavailableError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="PolkitAgentUnavailable",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(AuthorizationDeniedError)
    async def authorization_denied_handler(
        request: Request, exc: AuthorizationDeniedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="AuthorizationDenied",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(PermissionDeniedError)
    async def permission_denied_handler(
        request: Request, exc: PermissionDeniedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="PermissionDeniedError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteDeviceNotTrustedError)
    async def remote_not_trusted_handler(
        request: Request, exc: RemoteDeviceNotTrustedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="RemoteDeviceNotTrustedError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteDeviceRevokedError)
    async def remote_revoked_handler(
        request: Request, exc: RemoteDeviceRevokedError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="RemoteDeviceRevokedError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(RemoteAuthorizationMissingError)
    async def remote_auth_missing_handler(
        request: Request, exc: RemoteAuthorizationMissingError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_403_FORBIDDEN,
            content=ErrorDetail(
                error="RemoteAuthorizationMissingError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(InvalidServiceNameError)
    async def invalid_service_name_handler(
        request: Request, exc: InvalidServiceNameError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorDetail(
                error="InvalidServiceNameError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(ServiceOperationError)
    async def service_operation_handler(
        request: Request, exc: ServiceOperationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_400_BAD_REQUEST,
            content=ErrorDetail(
                error="ServiceOperationError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(SystemdConnectionError)
    async def systemd_connection_handler(
        request: Request, exc: SystemdConnectionError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content=ErrorDetail(
                error="SystemdConnectionError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    @app.exception_handler(ServiceDeckError)
    async def generic_servicedeck_handler(request: Request, exc: ServiceDeckError) -> JSONResponse:
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content=ErrorDetail(
                error="ServiceDeckError",
                message=exc.message,
                details=exc.details,
            ).model_dump(),
        )

    return app
