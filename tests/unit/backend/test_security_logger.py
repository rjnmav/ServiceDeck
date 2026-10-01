"""Unit tests for the servicedeck.security structured audit logger."""

import logging

import pytest

from servicedeck.backend.core import security_logger


def test_log_operation_attempt(caplog: pytest.LogCaptureFixture) -> None:
    """log_operation_attempt logs structured operation and outcome."""
    with caplog.at_level(logging.INFO, logger="servicedeck.security"):
        security_logger.log_operation_attempt("restart", "nginx.service", "system", "success")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "INFO"
    assert "EVENT=service_operation" in record.message
    assert "operation=restart" in record.message
    assert "service=nginx.service" in record.message
    assert "scope=system" in record.message
    assert "outcome=success" in record.message


def test_log_authorization_denied(caplog: pytest.LogCaptureFixture) -> None:
    """log_authorization_denied logs warning with operation and reason."""
    with caplog.at_level(logging.WARNING, logger="servicedeck.security"):
        security_logger.log_authorization_denied(
            "stop", "docker.service", "system", "Polkit denied access"
        )

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert "EVENT=authorization_denied" in record.message
    assert "operation=stop" in record.message
    assert "service=docker.service" in record.message
    assert "scope=system" in record.message
    assert "Polkit denied access" in record.message


def test_log_polkit_agent_unavailable(caplog: pytest.LogCaptureFixture) -> None:
    """log_polkit_agent_unavailable logs agent failure."""
    with caplog.at_level(logging.WARNING, logger="servicedeck.security"):
        security_logger.log_polkit_agent_unavailable("start", "my-app.service", "system")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "WARNING"
    assert "EVENT=polkit_agent_unavailable" in record.message
    assert "operation=start" in record.message
    assert "service=my-app.service" in record.message


def test_log_scope_change(caplog: pytest.LogCaptureFixture) -> None:
    """log_scope_change logs active scope toggles."""
    with caplog.at_level(logging.INFO, logger="servicedeck.security"):
        security_logger.log_scope_change(old_scope="user", new_scope="system")

    assert len(caplog.records) == 1
    record = caplog.records[0]
    assert record.levelname == "INFO"
    assert "EVENT=scope_change" in record.message
    assert "old_scope=user" in record.message
    assert "new_scope=system" in record.message
