"""ServiceDeck API Client library.

Provides synchronous and asynchronous clients to interact with the
ServiceDeck REST API backend without direct D-Bus or Qt dependencies.
"""

from servicedeck.api_client.async_client import AsyncServiceDeckClient
from servicedeck.api_client.client import ServiceDeckClient
from servicedeck.api_client.exceptions import (
    BackendUnavailableError,
    InvalidServiceNameError,
    PolkitAgentUnavailableError,
    RemoteAuthorizationMissingError,
    RemoteConnectionError,
    RemoteDeviceNotTrustedError,
    RemoteDeviceRevokedError,
    RemoteHostKeyChangedError,
    ServiceAuthenticationRequiredError,
    ServiceAuthorizationDeniedError,
    ServiceDeckAPIError,
    ServiceDeckConnectionError,
    ServiceDeckHTTPError,
    ServiceNotFoundError,
    ServiceOperationError,
    ServicePermissionDeniedError,
    SSHAuthenticationError,
)
from servicedeck.api_client.models.common import HealthInfo, ScopeInfo
from servicedeck.api_client.models.remote import RemoteConnectionInfo, RemoteDevice
from servicedeck.api_client.models.service import (
    CreatedService,
    DaemonReloadResult,
    Service,
    ServiceLogs,
    ServiceOperationResult,
    ServiceResources,
    ServiceUnitFile,
)

__all__ = [
    "AsyncServiceDeckClient",
    "BackendUnavailableError",
    "CreatedService",
    "DaemonReloadResult",
    "HealthInfo",
    "InvalidServiceNameError",
    "PolkitAgentUnavailableError",
    "RemoteAuthorizationMissingError",
    "RemoteConnectionError",
    "RemoteConnectionInfo",
    "RemoteDevice",
    "RemoteDeviceNotTrustedError",
    "RemoteDeviceRevokedError",
    "RemoteHostKeyChangedError",
    "SSHAuthenticationError",
    "ScopeInfo",
    "Service",
    "ServiceAuthenticationRequiredError",
    "ServiceAuthorizationDeniedError",
    "ServiceDeckAPIError",
    "ServiceDeckClient",
    "ServiceDeckConnectionError",
    "ServiceDeckHTTPError",
    "ServiceLogs",
    "ServiceNotFoundError",
    "ServiceOperationError",
    "ServiceOperationResult",
    "ServicePermissionDeniedError",
    "ServiceResources",
    "ServiceUnitFile",
]
