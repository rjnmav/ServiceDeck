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
    ServiceDeckStreamError,
    ServiceNotFoundError,
    ServiceOperationError,
    ServicePermissionDeniedError,
    SSHAuthenticationError,
)
from servicedeck.api_client.models.common import HealthInfo, ScopeInfo
from servicedeck.api_client.models.remote import (
    HostKeyInfo,
    KeySetupInfo,
    RemoteConnectionInfo,
    RemoteDevice,
)
from servicedeck.api_client.models.service import (
    CreatedService,
    DaemonReloadResult,
    Service,
    ServiceEvent,
    ServiceLogs,
    ServiceOperationResult,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.api_client.streaming import EventStream

__all__ = [
    "AsyncServiceDeckClient",
    "BackendUnavailableError",
    "CreatedService",
    "DaemonReloadResult",
    "EventStream",
    "HealthInfo",
    "HostKeyInfo",
    "InvalidServiceNameError",
    "KeySetupInfo",
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
    "ServiceDeckStreamError",
    "ServiceEvent",
    "ServiceLogs",
    "ServiceNotFoundError",
    "ServiceOperationError",
    "ServiceOperationResult",
    "ServicePermissionDeniedError",
    "ServiceResources",
    "ServiceUnitFile",
]
