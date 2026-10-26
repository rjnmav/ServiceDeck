"""ServiceDeck 2.0 remote protocol layer.

Shared protocol definitions, message types, framing, and serialization
used by both the local SSH transport and the remote servicedeck-remote agent.
"""

from servicedeck.remote.exceptions import (
    RemoteProtocolError,
    RemoteTimeoutError,
    UnknownMethodError,
)
from servicedeck.remote.models import (
    PROTOCOL_VERSION,
    AuthChallengeMessage,
    AuthResponseMessage,
    ErrorDetail,
    GoodbyeMessage,
    HelloMessage,
    ProtocolMessage,
    RequestMessage,
    ResponseMessage,
    error_response,
    success_response,
)
from servicedeck.remote.protocol import (
    ProtocolDecoder,
    ProtocolEncoder,
    read_message,
    write_message,
)

__all__ = [
    "PROTOCOL_VERSION",
    "AuthChallengeMessage",
    "AuthResponseMessage",
    "ErrorDetail",
    "GoodbyeMessage",
    "HelloMessage",
    "ProtocolDecoder",
    "ProtocolEncoder",
    "ProtocolMessage",
    "RemoteProtocolError",
    "RemoteTimeoutError",
    "RequestMessage",
    "ResponseMessage",
    "UnknownMethodError",
    "error_response",
    "read_message",
    "success_response",
    "write_message",
]
