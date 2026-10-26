"""Unit tests for remote protocol framing, encoder, and decoder."""

import asyncio
import json

import pytest

from servicedeck.remote.exceptions import RemoteProtocolError
from servicedeck.remote.models import (
    HelloMessage,
    RequestMessage,
    error_response,
    success_response,
)
from servicedeck.remote.protocol import (
    ProtocolDecoder,
    ProtocolEncoder,
    read_message,
)


class TestProtocolEncoder:
    """Tests for ProtocolEncoder."""

    def setup_method(self) -> None:
        self.encoder = ProtocolEncoder()

    def test_encode_hello_message(self) -> None:
        msg = HelloMessage(host="node1", user="alice", uid=1000, servicedeck_version="2.0.0")
        raw = self.encoder.encode(msg)

        # Wire format: <len>\n<json>\n
        parts = raw.split(b"\n", 1)
        length = int(parts[0])
        payload_with_trailing = parts[1]
        payload = payload_with_trailing[:length]
        trailing = payload_with_trailing[length:]

        assert trailing == b"\n"
        data = json.loads(payload)
        assert data["type"] == "hello"
        assert data["host"] == "node1"
        assert data["user"] == "alice"
        assert data["uid"] == 1000

    def test_encode_request_message(self) -> None:
        msg = RequestMessage(id=42, method="service.restart", params={"name": "nginx"})
        raw = self.encoder.encode(msg)
        parts = raw.split(b"\n", 1)
        length = int(parts[0])
        data = json.loads(parts[1][:length])

        assert data["type"] == "request"
        assert data["id"] == 42
        assert data["method"] == "service.restart"
        assert data["params"] == {"name": "nginx"}

    def test_encode_success_response_strips_none_error(self) -> None:
        msg = success_response(10, result={"ok": True})
        raw = self.encoder.encode(msg)
        parts = raw.split(b"\n", 1)
        length = int(parts[0])
        data = json.loads(parts[1][:length])

        assert data["type"] == "response"
        assert data["id"] == 10
        assert data["success"] is True
        assert "error" not in data

    def test_encode_error_response(self) -> None:
        msg = error_response(11, "SERVICE_NOT_FOUND", "No such service")
        raw = self.encoder.encode(msg)
        parts = raw.split(b"\n", 1)
        length = int(parts[0])
        data = json.loads(parts[1][:length])

        assert data["type"] == "response"
        assert data["id"] == 11
        assert data["success"] is False
        assert data["error"]["code"] == "SERVICE_NOT_FOUND"


class TestProtocolDecoder:
    """Tests for streaming ProtocolDecoder."""

    def setup_method(self) -> None:
        self.decoder = ProtocolDecoder()
        self.encoder = ProtocolEncoder()

    def test_decode_single_message(self) -> None:
        msg = HelloMessage(host="srv", user="bob", uid=1001)
        raw = self.encoder.encode(msg)

        self.decoder.feed(raw)
        messages = self.decoder.get_messages()

        assert len(messages) == 1
        decoded = messages[0]
        assert isinstance(decoded, HelloMessage)
        assert decoded.host == "srv"
        assert decoded.user == "bob"
        assert decoded.uid == 1001

    def test_decode_multiple_messages_in_one_feed(self) -> None:
        msg1 = RequestMessage(id=1, method="service.list")
        msg2 = RequestMessage(id=2, method="service.get", params={"name": "ssh"})
        raw = self.encoder.encode(msg1) + self.encoder.encode(msg2)

        self.decoder.feed(raw)
        messages = self.decoder.get_messages()

        assert len(messages) == 2
        assert isinstance(messages[0], RequestMessage)
        assert messages[0].id == 1
        assert isinstance(messages[1], RequestMessage)
        assert messages[1].id == 2

    def test_decode_partial_chunks(self) -> None:
        msg = RequestMessage(id=99, method="service.restart", params={"name": "nginx"})
        raw = self.encoder.encode(msg)

        chunk1 = raw[: len(raw) // 2]
        chunk2 = raw[len(raw) // 2 :]

        self.decoder.feed(chunk1)
        assert self.decoder.get_messages() == []

        self.decoder.feed(chunk2)
        messages = self.decoder.get_messages()
        assert len(messages) == 1
        assert messages[0].id == 99

    def test_decode_invalid_length_header(self) -> None:
        self.decoder.feed(b"invalid_number\n{\"type\":\"goodbye\"}\n")
        with pytest.raises(RemoteProtocolError, match="Invalid frame length header"):
            self.decoder.get_messages()

    def test_decode_missing_trailing_newline(self) -> None:
        payload = b'{"type":"goodbye","reason":"shutdown"}'
        frame = f"{len(payload)}\n".encode() + payload + b"X"  # 'X' instead of '\n'
        self.decoder.feed(frame)
        with pytest.raises(RemoteProtocolError, match="Missing expected trailing newline"):
            self.decoder.get_messages()

    def test_decode_invalid_json(self) -> None:
        payload = b"{not json}"
        frame = f"{len(payload)}\n".encode() + payload + b"\n"
        self.decoder.feed(frame)
        with pytest.raises(RemoteProtocolError, match="Invalid JSON payload"):
            self.decoder.get_messages()

    def test_decode_unknown_message_type(self) -> None:
        payload = b'{"type":"alien_message"}'
        frame = f"{len(payload)}\n".encode() + payload + b"\n"
        self.decoder.feed(frame)
        with pytest.raises(RemoteProtocolError, match="Unknown protocol message type"):
            self.decoder.get_messages()


class TestAsyncStreamIO:
    """Tests for async read_message and write_message functions."""

    async def test_read_message_success(self) -> None:
        msg = RequestMessage(id=1, method="health.check")
        encoder = ProtocolEncoder()
        raw = encoder.encode(msg)

        reader = asyncio.StreamReader()
        reader.feed_data(raw)

        decoded = await read_message(reader)
        assert isinstance(decoded, RequestMessage)
        assert decoded.id == 1
        assert decoded.method == "health.check"

    async def test_read_message_eof(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_eof()
        result = await read_message(reader)
        assert result is None

    async def test_read_message_incomplete(self) -> None:
        reader = asyncio.StreamReader()
        reader.feed_data(b"50\n{\"partial\": true")
        reader.feed_eof()

        with pytest.raises(RemoteProtocolError, match="Stream closed while reading"):
            await read_message(reader)
