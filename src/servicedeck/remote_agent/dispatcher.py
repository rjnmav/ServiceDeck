"""Request dispatcher mapping protocol messages to ServiceManager operations."""

import dataclasses
import logging
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
        except ServiceNotFoundError as exc:
            return error_response(
                request.id,
                "SERVICE_NOT_FOUND",
                exc.message,
                {"service_name": exc.service_name},
            )
        except InvalidServiceNameError as exc:
            return error_response(
                request.id,
                "INVALID_SERVICE_NAME",
                exc.message,
                {"service_name": exc.service_name},
            )
        except PolkitAgentUnavailableError as exc:
            return error_response(
                request.id,
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
                request.id,
                "AUTHORIZATION_DENIED",
                exc.message,
                {
                    "action": getattr(exc, "action", None),
                    "service_name": getattr(exc, "service_name", None),
                },
            )
        except AuthenticationRequiredError as exc:
            return error_response(
                request.id,
                "AUTHENTICATION_REQUIRED",
                exc.message,
                exc.details,
            )
        except PermissionDeniedError as exc:
            return error_response(
                request.id,
                "PERMISSION_DENIED",
                exc.message,
                {
                    "action": getattr(exc, "action", None),
                    "service_name": getattr(exc, "service_name", None),
                },
            )
        except ServiceOperationError as exc:
            return error_response(
                request.id,
                "SERVICE_OPERATION_FAILED",
                exc.message,
                {"service_name": exc.service_name, "operation": exc.operation},
            )
        except SystemdConnectionError as exc:
            return error_response(
                request.id,
                "SYSTEMD_CONNECTION_ERROR",
                exc.message,
                exc.details,
            )
        except ServiceDeckError as exc:
            return error_response(
                request.id,
                "SERVICEDECK_ERROR",
                exc.message,
                getattr(exc, "details", {}),
            )
        except ValueError as exc:
            return error_response(
                request.id,
                "INVALID_PARAMS",
                str(exc),
                {},
            )
        except Exception as exc:
            logger.exception("[%d] Unexpected error dispatching '%s': %s", request.id, method, exc)
            return error_response(
                request.id,
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
            resources = await self._manager.get_service_resources(
                name=params["name"], scope=scope
            )
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
    def _require_param(name: str, params: dict[str, Any]) -> None:
        """Validate that a required parameter is present in params."""
        if name not in params or params[name] is None:
            raise ValueError(f"Missing required parameter '{name}'")


__all__ = ["RequestDispatcher"]
