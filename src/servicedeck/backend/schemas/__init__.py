"""API schemas package."""

from servicedeck.backend.schemas.service import (
    ErrorDetail,
    HealthResponse,
    ScopeResponse,
    ScopeUpdateRequest,
    ServiceOperationResponse,
    ServiceResponse,
)

__all__ = [
    "ErrorDetail",
    "HealthResponse",
    "ScopeResponse",
    "ScopeUpdateRequest",
    "ServiceOperationResponse",
    "ServiceResponse",
]
