"""ServiceDeck 2.0 remote agent package.

Headless remote execution component launched via SSH.
Reads protocol requests from stdin, executes via ServiceManager + dbus-fast,
and writes structured responses to stdout.
"""

from servicedeck.remote_agent.dispatcher import RequestDispatcher
from servicedeck.remote_agent.server import ProtocolServer

__all__ = [
    "ProtocolServer",
    "RequestDispatcher",
]
