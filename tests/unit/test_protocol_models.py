"""Unit tests for remote protocol message models."""

import pytest

from servicedeck.remote.models import (
    PROTOCOL_VERSION,
    AuthChallengeMessage,
    AuthResponseMessage,
    ErrorDetail,
    GoodbyeMessage,
    HelloMessage,
    RequestMessage,
    ResponseMessage,
    error_response,
    success_response,
)


def test_protocol_version() -> None:
    assert PROTOCOL_VERSION == 1


def test_hello_message_defaults() -> None:
    msg = HelloMessage()
    assert msg.type == "hello"
    assert msg.version == PROTOCOL_VERSION
    assert msg.host == ""
    assert msg.user == ""
    assert msg.uid == -1
    assert msg.servicedeck_version == ""


def test_hello_message_custom_values() -> None:
    msg = HelloMessage(host="node1", user="testuser", uid=1001, servicedeck_version="2.0.0")
    assert msg.host == "node1"
    assert msg.user == "testuser"
    assert msg.uid == 1001
    assert msg.servicedeck_version == "2.0.0"


def test_request_message_defaults() -> None:
    msg = RequestMessage(id=1, method="service.list")
    assert msg.type == "request"
    assert msg.id == 1
    assert msg.method == "service.list"
    assert msg.params == {}


def test_request_message_with_params() -> None:
    msg = RequestMessage(id=42, method="service.restart", params={"name": "nginx.service"})
    assert msg.id == 42
    assert msg.method == "service.restart"
    assert msg.params == {"name": "nginx.service"}


def test_response_message_success() -> None:
    msg = ResponseMessage(id=1, success=True, result={"status": "ok"})
    assert msg.type == "response"
    assert msg.id == 1
    assert msg.success is True
    assert msg.result == {"status": "ok"}
    assert msg.error is None


def test_response_message_error() -> None:
    err = ErrorDetail(code="SERVICE_NOT_FOUND", message="Not found", details={"name": "foo"})
    msg = ResponseMessage(id=2, success=False, error=err)
    assert msg.success is False
    assert msg.error is not None
    assert msg.error.code == "SERVICE_NOT_FOUND"
    assert msg.error.message == "Not found"
    assert msg.error.details == {"name": "foo"}


def test_auth_challenge_message() -> None:
    msg = AuthChallengeMessage(id=5, challenge="password", prompt="Enter password:", echo=False)
    assert msg.type == "auth_challenge"
    assert msg.id == 5
    assert msg.challenge == "password"
    assert msg.prompt == "Enter password:"
    assert msg.echo is False


def test_auth_response_message() -> None:
    msg = AuthResponseMessage(id=5, response="supersecret")
    assert msg.type == "auth_response"
    assert msg.id == 5
    assert msg.response == "supersecret"


def test_goodbye_message() -> None:
    msg = GoodbyeMessage()
    assert msg.type == "goodbye"
    assert msg.reason == "shutdown"

    custom_goodbye = GoodbyeMessage(reason="disconnect")
    assert custom_goodbye.reason == "disconnect"


def test_success_response_helper() -> None:
    msg = success_response(10, {"count": 5})
    assert msg.id == 10
    assert msg.success is True
    assert msg.result == {"count": 5}
    assert msg.error is None


def test_error_response_helper() -> None:
    msg = error_response(11, "ACCESS_DENIED", "Permission denied", {"action": "stop"})
    assert msg.id == 11
    assert msg.success is False
    assert msg.result is None
    assert msg.error is not None
    assert msg.error.code == "ACCESS_DENIED"
    assert msg.error.message == "Permission denied"
    assert msg.error.details == {"action": "stop"}


def test_immutability() -> None:
    msg = HelloMessage(host="srv1")
    with pytest.raises(AttributeError):
        msg.host = "srv2"  # type: ignore[misc]
