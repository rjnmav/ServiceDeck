"""Request dispatcher mapping protocol messages to ServiceManager operations."""

import dataclasses
import logging
from collections.abc import AsyncIterator
from typing import Any

from servicedeck.backend.core.service_manager import ServiceManager
from servicedeck.backend.exceptions import (
    AuthenticationRequiredError,
    AuthorizationDeniedError,
    InvalidServiceNameError,
    PermissionDeniedError,
    PolkitAgentUnavailableError,
    ServiceDeckError,
    ServiceNotFoundError,
    ServiceOperationError,
    SystemdConnectionError,
)
from servicedeck.remote.models import (
    RequestMessage,
    ResponseMessage,
    error_response,
    success_response,
)

logger = logging.getLogger(__name__)

#: Methods that open a stream: answered once, then followed by ``event`` messages.
STREAM_METHODS = frozenset({"stream.services", "stream.logs"})

StreamItem = tuple[str, Any]


class RequestDispatcher:
    """Maps protocol method names to ServiceManager async method calls.

    Catches all domain exceptions and converts them into structured protocol
    error responses with machine-readable error codes.
    """

    def __init__(self, service_manager: ServiceManager) -> None:
        self._manager = service_manager

    async def dispatch(self, request: RequestMessage) -> ResponseMessage:
        """Dispatch a single protocol RequestMessage and return a ResponseMessage."""
        method = request.method
        params = request.params or {}

        logger.debug("[%d] Dispatching method '%s'", request.id, method)

        try:
            result = await self._execute_method(method, params)
            return success_response(request.id, result)
        except Exception as exc:
            if not isinstance(exc, ServiceDeckError | ValueError):
                logger.exception(
                    "[%d] Unexpected error dispatching '%s': %s", request.id, method, exc
                )
            return self.error_response_for(request.id, exc)

    @staticmethod
    def error_response_for(request_id: int, exc: BaseException) -> ResponseMessage:
        """Map an exception to the protocol error response the client understands."""
        try:
            raise exc
        except ServiceNotFoundError as exc:
            return error_response(
                request_id,
                "SERVICE_NOT_FOUND",
                exc.message,
                {"service_name": exc.service_name},
            )
        except InvalidServiceNameError as exc:
            return error_response(
                request_id,
                "INVALID_SERVICE_NAME",
                exc.message,
                {"service_name": exc.service_name},
            )
        except PolkitAgentUnavailableError as exc:
            return error_response(
                request_id,
                "AUTHENTICATION_REQUIRED",
                exc.message,
                {
                    "action": getattr(exc, "action", None),
                    "service_name": getattr(exc, "service_name", None),
                    "scope": getattr(exc, "scope", None),
                },
            )
        except AuthorizationDeniedError as exc:
            return error_response(
                request_id,
                "AUTHORIZATION_DENIED",
                exc.message,
                {
                    "action": getattr(exc, "action", None),
                    "service_name": getattr(exc, "service_name", None),
                },
            )
        except AuthenticationRequiredError as exc:
            return error_response(
                request_id,
                "AUTHENTICATION_REQUIRED",
                exc.message,
                exc.details,
            )
        except PermissionDeniedError as exc:
            return error_response(
                request_id,
                "PERMISSION_DENIED",
                exc.message,
                {
                    "action": getattr(exc, "action", None),
                    "service_name": getattr(exc, "service_name", None),
                },
            )
        except ServiceOperationError as exc:
            return error_response(
                request_id,
                "SERVICE_OPERATION_FAILED",
                exc.message,
                {"service_name": exc.service_name, "operation": exc.operation},
            )
        except SystemdConnectionError as exc:
            return error_response(
                request_id,
                "SYSTEMD_CONNECTION_ERROR",
                exc.message,
                exc.details,
            )
        except ServiceDeckError as exc:
            return error_response(
                request_id,
                "SERVICEDECK_ERROR",
                exc.message,
                getattr(exc, "details", {}),
            )
        except ValueError as exc:
            return error_response(
                request_id,
                "INVALID_PARAMS",
                str(exc),
                {},
            )
        except Exception as exc:
            return error_response(
                request_id,
                "INTERNAL_ERROR",
                f"An unexpected internal error occurred: {exc}",
                {"error": str(exc)},
            )

    async def _execute_method(self, method: str, params: dict[str, Any]) -> Any:
        """Route to and execute the appropriate ServiceManager method."""
        scope = params.get("scope")

        if method == "service.list":
            services = await self._manager.list_services(scope=scope)
            return [dataclasses.asdict(svc) for svc in services]

        if method == "service.get":
            self._require_param("name", params)
            service = await self._manager.get_service(name=params["name"], scope=scope)
            return dataclasses.asdict(service)

        if method == "service.start":
            self._require_param("name", params)
            await self._manager.start_service(name=params["name"], scope=scope)
            return None

        if method == "service.stop":
            self._require_param("name", params)
            await self._manager.stop_service(name=params["name"], scope=scope)
            return None

        if method == "service.restart":
            self._require_param("name", params)
            await self._manager.restart_service(name=params["name"], scope=scope)
            return None

        if method == "service.reload":
            self._require_param("name", params)
            await self._manager.reload_service(name=params["name"], scope=scope)
            return None

        if method == "service.enable":
            self._require_param("name", params)
            await self._manager.enable_service(name=params["name"], scope=scope)
            return None

        if method == "service.disable":
            self._require_param("name", params)
            await self._manager.disable_service(name=params["name"], scope=scope)
            return None

        if method == "service.mask":
            self._require_param("name", params)
            await self._manager.mask_service(name=params["name"], scope=scope)
            return None

        if method == "service.unmask":
            self._require_param("name", params)
            await self._manager.unmask_service(name=params["name"], scope=scope)
            return None

        if method == "daemon.reload":
            await self._manager.reload_daemon(scope=scope)
            return None

        if method == "service.unit_file":
            self._require_param("name", params)
            path, content = await self._manager.get_unit_file(name=params["name"], scope=scope)
            return {"path": path, "content": content}

        if method == "service.resources":
            self._require_param("name", params)
            resources = await self._manager.get_service_resources(name=params["name"], scope=scope)
            return dataclasses.asdict(resources)

        if method == "service.logs":
            self._require_param("name", params)
            lines = params.get("lines", 200)
            logs = await self._manager.get_service_logs(
                name=params["name"], lines=lines, scope=scope
            )
            return {"logs": logs}

        if method == "service.create":
            self._require_param("name", params)
            self._require_param("content", params)
            path = await self._manager.create_service(
                name=params["name"],
                content=params["content"],
                scope=scope,
                overwrite=params.get("overwrite", False),
            )
            return {"path": path}

        if method == "health.check":
            healthy = await self._manager.is_healthy(scope=scope)
            return {"healthy": healthy}

        raise ValueError(f"Unknown method '{method}'")

    @staticmethod
    def is_stream_method(method: str) -> bool:
        """Return True if ``method`` opens a stream instead of returning one result."""
        return method in STREAM_METHODS

    def open_stream(self, method: str, params: dict[str, Any]) -> AsyncIterator[StreamItem]:
        """Start a stream; yields ``(event, data)`` pairs, the first being ``("ready", ...)``.

        Raising before the first item means the stream could not be opened; the caller
        answers the request with :meth:`error_response_for` in that case.
        """
        if method == "stream.services":
            return self._service_events(params.get("scope"))
        if method == "stream.logs":
            self._require_param("name", params)
            return self._log_lines(
                params["name"], int(params.get("lines", 200)), params.get("scope")
            )
        raise ValueError(f"Unknown stream method '{method}'")

    async def _service_events(self, scope: str | None) -> AsyncIterator[StreamItem]:
        events = self._manager.watch_services(scope=scope)
        try:
            async for event in events:
                if event.kind == "changed" and event.service is not None:
                    yield "service", dataclasses.asdict(event.service)
                elif event.kind == "removed":
                    yield "removed", {"name": event.name, "scope": event.scope}
                else:
                    yield event.kind, {"scope": event.scope}
        finally:
            await events.aclose()  # type: ignore[attr-defined]

    async def _log_lines(
        self, name: str, lines: int, scope: str | None
    ) -> AsyncIterator[StreamItem]:
        stream = self._manager.follow_service_logs(name=name, lines=lines, scope=scope)
        try:
            first = True
            async for line in stream:
                if first:
                    first = False
                    yield "ready", None
                    continue
                yield "log", {"line": line}
        finally:
            await stream.aclose()  # type: ignore[attr-defined]

    @staticmethod
    def _require_param(name: str, params: dict[str, Any]) -> None:
        """Validate that a required parameter is present in params."""
        if name not in params or params[name] is None:
            raise ValueError(f"Missing required parameter '{name}'")


__all__ = ["RequestDispatcher"]
