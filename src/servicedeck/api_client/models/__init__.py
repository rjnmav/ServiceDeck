"""Domain models for the ServiceDeck API client."""

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
    "CreatedService",
    "DaemonReloadResult",
    "HealthInfo",
    "RemoteConnectionInfo",
    "RemoteDevice",
    "ScopeInfo",
    "Service",
    "ServiceLogs",
    "ServiceOperationResult",
    "ServiceResources",
    "ServiceUnitFile",
]
