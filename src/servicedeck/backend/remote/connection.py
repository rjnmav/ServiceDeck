"""Connection manager coordinating active SSH transports to remote devices."""

from __future__ import annotations

import logging

from servicedeck.backend.exceptions import RemoteConnectionError
from servicedeck.backend.remote.device_config import RemoteDevice
from servicedeck.backend.remote.known_hosts import KnownHostsStore
from servicedeck.backend.remote.transport import SSHTransport
from servicedeck.remote.models import HelloMessage

logger = logging.getLogger(__name__)


class RemoteConnectionManager:
    """Manages active SSH transport connections to remote ServiceDeck devices."""

    def __init__(self, known_hosts: KnownHostsStore | None = None) -> None:
        self._transports: dict[str, SSHTransport] = {}
        self._known_hosts = known_hosts or KnownHostsStore()

    @property
    def known_hosts(self) -> KnownHostsStore:
        """Host-key trust store shared by all transports."""
        return self._known_hosts

    def is_connected(self, device_id: str) -> bool:
        """Return True if an active transport exists and is connected for device_id."""
        transport = self._transports.get(device_id)
        return transport is not None and transport.is_connected

    def get_transport(self, device_id: str) -> SSHTransport | None:
        """Retrieve the active SSH transport for device_id, or None if not connected."""
        transport = self._transports.get(device_id)
        if transport is not None and transport.is_connected:
            return transport
        return None

    def list_connected(self) -> list[str]:
        """Return a list of device IDs that currently have active connections."""
        return [
            dev_id
            for dev_id, transport in self._transports.items()
            if transport.is_connected
        ]

    async def connect(
        self,
        device: RemoteDevice,
        timeout: float = 15.0,
        remote_command: str = "servicedeck-remote",
    ) -> HelloMessage:
        """Establish or reuse an active SSH transport connection to device."""
        existing = self._transports.get(device.id)
        if existing is not None and existing.is_connected and existing.hello is not None:
            logger.debug("Reusing active transport for device '%s'", device.id)
            return existing.hello

        # Disconnect any stale transport
        if existing is not None:
            await existing.disconnect()
            self._transports.pop(device.id, None)

        transport = SSHTransport(
            device=device, remote_command=remote_command, known_hosts=self._known_hosts
        )
        hello = await transport.connect(timeout=timeout)
        self._transports[device.id] = transport
        return hello

    def is_elevated(self, device_id: str) -> bool:
        """Return True if device_id has a running administrator (root) agent."""
        transport = self._transports.get(device_id)
        return transport is not None and transport.is_elevated

    async def elevate(
        self, device_id: str, password: str | None, timeout: float = 30.0
    ) -> HelloMessage:
        """Start the root agent for an already-connected device."""
        transport = self.get_transport(device_id)
        if transport is None:
            raise RemoteConnectionError(
                f"Device '{device_id}' is not connected.", details={"device_id": device_id}
            )
        return await transport.elevate(password, timeout=timeout)

    async def drop_privileges(self, device_id: str) -> None:
        """Stop the root agent for device_id, keeping the normal connection."""
        transport = self._transports.get(device_id)
        if transport is not None:
            await transport.drop_privileges()

    async def disconnect(self, device_id: str) -> None:
        """Disconnect and remove transport for device_id."""
        transport = self._transports.pop(device_id, None)
        if transport is not None:
            await transport.disconnect()

    async def disconnect_all(self) -> None:
        """Disconnect all active device transports."""
        transports = list(self._transports.values())
        self._transports.clear()
        for transport in transports:
            try:
                await transport.disconnect()
            except Exception as exc:
                logger.warning("Error disconnecting transport for %s: %s", transport.device.id, exc)


__all__ = ["RemoteConnectionManager"]
