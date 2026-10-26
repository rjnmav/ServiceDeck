"""Wire format framing, encoding, and decoding for the ServiceDeck remote protocol."""

import asyncio
import json
from dataclasses import asdict

from servicedeck.remote.exceptions import RemoteProtocolError
from servicedeck.remote.models import (
    AuthChallengeMessage,
    AuthResponseMessage,
    ErrorDetail,
    GoodbyeMessage,
    HelloMessage,
    ProtocolMessage,
    RequestMessage,
    ResponseMessage,
)


def _parse_message(payload: bytes) -> ProtocolMessage:
    """Parse JSON payload bytes into a typed protocol message dataclass."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise RemoteProtocolError(
            f"Invalid JSON payload: {exc}",
            details={"error": str(exc)},
        ) from exc

    if not isinstance(data, dict):
        raise RemoteProtocolError(
            f"Payload must be a JSON object, got {type(data).__name__}",
            details={"type": type(data).__name__},
        )

    msg_type = data.get("type")
    if msg_type == "hello":
        return HelloMessage(**data)
    if msg_type == "request":
        return RequestMessage(**data)
    if msg_type == "response":
        error_dict = data.get("error")
        if isinstance(error_dict, dict):
            data["error"] = ErrorDetail(**error_dict)
        elif error_dict is not None and not isinstance(error_dict, ErrorDetail):
            raise RemoteProtocolError("Invalid error structure in response")
        return ResponseMessage(**data)
    if msg_type == "auth_challenge":
        return AuthChallengeMessage(**data)
    if msg_type == "auth_response":
        return AuthResponseMessage(**data)
    if msg_type == "goodbye":
        return GoodbyeMessage(**data)

    raise RemoteProtocolError(
        f"Unknown protocol message type: '{msg_type}'",
        details={"type": msg_type},
    )


class ProtocolEncoder:
    """Encodes protocol messages to length-prefixed JSON wire frames.

    Frame format: <byte_length_in_ascii>\n<json_payload>\n
    """

    def encode(self, message: ProtocolMessage) -> bytes:
        """Encode a protocol message into wire frame bytes."""
        payload_dict = asdict(message)
        if isinstance(message, ResponseMessage) and payload_dict.get("error") is None:
            payload_dict.pop("error", None)

        json_bytes = json.dumps(payload_dict, separators=(",", ":")).encode("utf-8")
        header = f"{len(json_bytes)}\n".encode("ascii")
        return header + json_bytes + b"\n"


class ProtocolDecoder:
    """Streaming decoder for length-prefixed JSON frames.

    Buffers incoming bytes, extracts full frames, and parses them into protocol messages.
    """

    def __init__(self) -> None:
        self._buffer = bytearray()

    def feed(self, data: bytes) -> None:
        """Append incoming transport bytes to the internal buffer."""
        self._buffer.extend(data)

    def get_messages(self) -> list[ProtocolMessage]:
        """Extract and return all complete protocol messages currently in the buffer."""
        messages: list[ProtocolMessage] = []

        while True:
            newline_pos = self._buffer.find(b"\n")
            if newline_pos == -1:
                break

            header_bytes = self._buffer[:newline_pos]
            try:
                length_str = header_bytes.decode("ascii")
                payload_len = int(length_str)
                if payload_len < 0:
                    raise ValueError("Negative frame length")
            except (ValueError, UnicodeDecodeError) as exc:
                raise RemoteProtocolError(
                    f"Invalid frame length header: {header_bytes!r}",
                    details={"raw": header_bytes.decode("ascii", errors="replace")},
                ) from exc

            frame_total_len = newline_pos + 1 + payload_len + 1  # header\n + payload + \n
            if len(self._buffer) < frame_total_len:
                break  # Incomplete frame, wait for more data

            payload_bytes = bytes(self._buffer[newline_pos + 1 : newline_pos + 1 + payload_len])
            trailing_delimiter = self._buffer[newline_pos + 1 + payload_len]

            if trailing_delimiter != ord(b"\n"):
                raise RemoteProtocolError(
                    "Missing expected trailing newline after payload",
                    details={"byte": chr(trailing_delimiter)},
                )

            del self._buffer[:frame_total_len]
            message = _parse_message(payload_bytes)
            messages.append(message)

        return messages


async def read_message(reader: asyncio.StreamReader) -> ProtocolMessage | None:
    """Read a single length-prefixed protocol message from an asyncio stream.

    Returns None on EOF if no bytes were read.
    """
    length_line = await reader.readline()
    if not length_line:
        return None

    try:
        length_str = length_line.decode("ascii").strip()
        payload_len = int(length_str)
        if payload_len < 0:
            raise ValueError("Negative frame length")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RemoteProtocolError(
            f"Invalid frame length header in stream: {length_line!r}",
            details={"raw": length_line.decode("ascii", errors="replace")},
        ) from exc

    try:
        payload = await reader.readexactly(payload_len)
        trailing_newline = await reader.readexactly(1)
    except asyncio.IncompleteReadError as exc:
        raise RemoteProtocolError(
            "Stream closed while reading framed message payload",
            details={"expected_bytes": payload_len},
        ) from exc

    if trailing_newline != b"\n":
        raise RemoteProtocolError("Missing trailing newline delimiter after payload")

    return _parse_message(payload)


async def write_message(writer: asyncio.StreamWriter, message: ProtocolMessage) -> None:
    """Encode and write a protocol message to an asyncio stream writer, draining the buffer."""
    encoder = ProtocolEncoder()
    encoded_bytes = encoder.encode(message)
    writer.write(encoded_bytes)
    await writer.drain()


__all__ = [
    "ProtocolDecoder",
    "ProtocolEncoder",
    "read_message",
    "write_message",
]
