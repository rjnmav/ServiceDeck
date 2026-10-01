"""D-Bus connection management for both User and System buses using dbus-fast."""

import logging
from typing import Self

from dbus_fast.aio import MessageBus
from dbus_fast.constants import BusType

from servicedeck.backend.config.settings import Settings, get_settings
from servicedeck.backend.exceptions import SystemdConnectionError
from servicedeck.backend.models.service import validate_scope

logger = logging.getLogger(__name__)


class DbusConnectionManager:
    """Manages asynchronous D-Bus connections for both User session bus and System bus."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._user_bus: MessageBus | None = None
        self._system_bus: MessageBus | None = None

    def is_connected(self, scope: str = "user") -> bool:
        """Return True if the D-Bus connection for the specified scope is active."""
        valid_scope = validate_scope(scope)
        bus = self._user_bus if valid_scope == "user" else self._system_bus
        return bus is not None and bus.connected

    async def connect(self, scope: str = "user") -> MessageBus:
        """Connect to the D-Bus bus corresponding to the specified scope."""
        valid_scope = validate_scope(scope)

        if self.is_connected(valid_scope):
            bus = self._user_bus if valid_scope == "user" else self._system_bus
            if bus is not None:
                return bus

        try:
            if valid_scope == "user":
                logger.info("Connecting to user session D-Bus")
                self._user_bus = await MessageBus(bus_type=BusType.SESSION).connect()
                logger.info("Connected to user session D-Bus successfully.")
                return self._user_bus
            else:
                if self._settings.dbus_address:
                    logger.info("Connecting to system D-Bus at %s", self._settings.dbus_address)
                    self._system_bus = await MessageBus(
                        bus_address=self._settings.dbus_address
                    ).connect()
                else:
                    logger.info("Connecting to system D-Bus")
                    self._system_bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
                logger.info("Connected to system D-Bus successfully.")
                return self._system_bus

        except Exception as exc:
            logger.error("Failed to connect to %s D-Bus: %s", valid_scope, exc)
            if valid_scope == "user":
                self._user_bus = None
            else:
                self._system_bus = None
            raise SystemdConnectionError(
                f"Failed to connect to {valid_scope} D-Bus: {exc}",
                details={"scope": valid_scope, "original_error": str(exc)},
            ) from exc

    async def get_bus(self, scope: str = "user") -> MessageBus:
        """Return active bus for the specified scope or establish connection."""
        valid_scope = validate_scope(scope)
        if not self.is_connected(valid_scope):
            return await self.connect(valid_scope)

        bus = self._user_bus if valid_scope == "user" else self._system_bus
        assert bus is not None
        return bus

    async def disconnect(self, scope: str | None = None) -> None:
        """Gracefully disconnect from D-Bus for a specific scope or all scopes."""
        targets = [validate_scope(scope)] if scope is not None else ["user", "system"]

        for target in targets:
            bus = self._user_bus if target == "user" else self._system_bus
            if bus is not None:
                try:
                    if bus.connected:
                        bus.disconnect()
                    logger.info("Disconnected from %s D-Bus.", target)
                except Exception as exc:
                    logger.warning("Error during %s D-Bus disconnect: %s", target, exc)
                finally:
                    if target == "user":
                        self._user_bus = None
                    else:
                        self._system_bus = None

    async def __aenter__(self) -> Self:
        await self.connect("user")
        try:
            await self.connect("system")
        except Exception as exc:
            logger.debug("Optional system D-Bus connection not established on enter: %s", exc)
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.disconnect()
