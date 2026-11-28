"""Desktop notifications through the freedesktop ``org.freedesktop.Notifications`` service.

Uses ``dbus-fast`` (already a dependency) on the session bus, so it works on any desktop
with a notification daemon (GNOME, KDE Plasma, dunst, mako, ...). Sending runs on a
worker thread; nothing blocks the Qt thread.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

APP_NAME = "ServiceDeck"
APP_ICON = "dialog-error"
NOTIFY_TIMEOUT_SECONDS = 5.0

#: Notification urgency hint (freedesktop spec): 0 low, 1 normal, 2 critical.
URGENCY_CRITICAL = 2


async def send_notification(summary: str, body: str, *, urgency: int = URGENCY_CRITICAL) -> int:
    """Show a desktop notification; returns its id. Raises if no notification service."""
    from dbus_fast import BusType, Message, MessageType, Variant
    from dbus_fast.aio import MessageBus

    bus = await asyncio.wait_for(
        MessageBus(bus_type=BusType.SESSION).connect(), timeout=NOTIFY_TIMEOUT_SECONDS
    )
    try:
        reply = await asyncio.wait_for(
            bus.call(
                Message(
                    destination="org.freedesktop.Notifications",
                    path="/org/freedesktop/Notifications",
                    interface="org.freedesktop.Notifications",
                    member="Notify",
                    signature="susssasa{sv}i",
                    body=[
                        APP_NAME,
                        0,
                        APP_ICON,
                        summary,
                        body,
                        [],
                        {"urgency": Variant("y", urgency)},
                        -1,
                    ],
                )
            ),
            timeout=NOTIFY_TIMEOUT_SECONDS,
        )
    finally:
        bus.disconnect()
    if reply is None or reply.message_type == MessageType.ERROR:
        error = reply.body[0] if reply is not None and reply.body else "no reply"
        raise RuntimeError(f"Notification service refused the notification: {error}")
    return int(reply.body[0]) if reply.body else 0


class DesktopNotifier:
    """Sends desktop notifications in the background and reports whether they worked."""

    def __init__(self, sender: Callable[[str, str], Any] | None = None) -> None:
        self._sender = sender or self._send_blocking

    @staticmethod
    def _send_blocking(summary: str, body: str) -> int:
        return asyncio.run(send_notification(summary, body))

    def notify(
        self,
        summary: str,
        body: str,
        on_failed: Callable[[str], None] | None = None,
    ) -> None:
        """Queue a notification; ``on_failed(reason)`` runs on the Qt thread if it fails."""
        from servicedeck.gui.workers.service_worker import run_async_task

        def failed(message: str, _exc: Any) -> None:
            logger.info("Desktop notification failed: %s", message)
            if on_failed is not None:
                on_failed(message)

        run_async_task(self._sender, summary, body, on_error=failed)


__all__ = ["DesktopNotifier", "send_notification"]
