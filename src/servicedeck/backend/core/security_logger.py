"""Structured security event logging for ServiceDeck.

Logs security-relevant events without logging secrets.

Logged events:
    - Service lifecycle operations (start, stop, restart, reload, enable, disable)
    - Authorization grants and denials
    - Polkit agent availability failures
    - Active scope changes

Never logged:
    - Passwords
    - Private SSH keys
    - Authentication tokens
    - Secret or key material
"""

import logging
from datetime import UTC, datetime

logger = logging.getLogger("servicedeck.security")


def _timestamp() -> str:
    """Return current UTC timestamp in ISO 8601 format."""
    return datetime.now(UTC).isoformat()


def log_operation_attempt(
    operation: str,
    service: str,
    scope: str,
    outcome: str,
    caller: str | None = None,
) -> None:
    """Log an attempted service operation and its outcome."""
    logger.info(
        "EVENT=service_operation timestamp=%s operation=%s service=%s scope=%s outcome=%s caller=%s",
        _timestamp(),
        operation,
        service,
        scope,
        outcome,
        caller or "local",
    )


def log_authorization_denied(
    operation: str,
    service: str,
    scope: str,
    reason: str,
    caller: str | None = None,
) -> None:
    """Log an authorization denial by Polkit or system policy."""
    logger.warning(
        "EVENT=authorization_denied timestamp=%s operation=%s service=%s scope=%s reason=%s caller=%s",
        _timestamp(),
        operation,
        service,
        scope,
        reason,
        caller or "local",
    )


def log_polkit_agent_unavailable(
    operation: str,
    service: str,
    scope: str,
    caller: str | None = None,
) -> None:
    """Log that an operation required interactive Polkit auth but no agent was available."""
    logger.warning(
        "EVENT=polkit_agent_unavailable timestamp=%s operation=%s service=%s scope=%s caller=%s",
        _timestamp(),
        operation,
        service,
        scope,
        caller or "local",
    )


def log_scope_change(
    old_scope: str,
    new_scope: str,
    caller: str | None = None,
) -> None:
    """Log an update to the active service scope."""
    logger.info(
        "EVENT=scope_change timestamp=%s old_scope=%s new_scope=%s caller=%s",
        _timestamp(),
        old_scope,
        new_scope,
        caller or "local",
    )
