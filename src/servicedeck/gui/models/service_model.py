"""Table model representing systemd services in PySide6."""

import dataclasses
import time
from typing import Any, ClassVar

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt, QTimer
from PySide6.QtGui import QColor, QFont

from servicedeck.api_client.models.service import Service

_DEFAULT_INDEX = QModelIndex()


class ServiceTableModel(QAbstractTableModel):
    """Qt Table Model displaying systemd service unit details."""

    COL_NAME = 0
    COL_DESCRIPTION = 1
    COL_ACTIVE_STATE = 2
    COL_SUB_STATE = 3
    COL_ENABLED = 4
    COL_COUNT = 5

    HEADER_LABELS: ClassVar[dict[int, str]] = {
        COL_NAME: "Service Name",
        COL_DESCRIPTION: "Description",
        COL_ACTIVE_STATE: "Active",
        COL_SUB_STATE: "Sub State",
        COL_ENABLED: "Enabled",
    }

    # Color definitions matching original ServiceDeck
    COLOR_SUCCESS = QColor(0x4C, 0xAF, 0x50)  # Green #4CAF50
    COLOR_DANGER = QColor(0xF4, 0x43, 0x36)  # Red #F44336
    COLOR_MUTED = QColor(0x9E, 0x9E, 0x9E)  # Gray #9E9E9E
    COLOR_WARNING = QColor(0xFF, 0xA7, 0x26)  # Orange #FFA726
    COLOR_BROWN = QColor(0x79, 0x55, 0x48)  # Brown #795548

    # Row tints for live state changes; translucent so they read on both themes.
    HIGHLIGHT_CHANGED = QColor(0x42, 0xA5, 0xF5, 70)  # Blue
    HIGHLIGHT_FAILED = QColor(0xF4, 0x43, 0x36, 90)  # Red
    #: Seconds a changed row stays highlighted.
    HIGHLIGHT_SECONDS = 4.0

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._services: list[Service] = []
        self._rows: dict[str, int] = {}
        self._highlights: dict[str, tuple[float, QColor]] = {}
        self._bold_font = QFont()
        self._bold_font.setBold(True)
        self._highlight_timer = QTimer(self)
        self._highlight_timer.setInterval(500)
        self._highlight_timer.timeout.connect(self.expire_highlights)

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX) -> int:
        """Return the number of service rows."""
        if parent.isValid():
            return 0
        return len(self._services)

    def columnCount(self, parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX) -> int:
        """Return the number of columns."""
        if parent.isValid():
            return 0
        return self.COL_COUNT

    def data(
        self,
        index: QModelIndex | QPersistentModelIndex,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Provide data for the specified index and role."""
        if not index.isValid() or not (0 <= index.row() < len(self._services)):
            return None

        service = self._services[index.row()]
        col = index.column()

        if role == Qt.ItemDataRole.DisplayRole:
            if col == self.COL_NAME:
                return service.name
            if col == self.COL_DESCRIPTION:
                return service.description
            if col == self.COL_ACTIVE_STATE:
                return service.active_state.upper()
            if col == self.COL_SUB_STATE:
                return service.sub_state.lower()
            if col == self.COL_ENABLED:
                return service.unit_file_state.upper()

        elif role == Qt.ItemDataRole.ForegroundRole:
            if col == self.COL_ACTIVE_STATE:
                state = service.active_state.lower()
                if state == "active":
                    return self.COLOR_SUCCESS
                if state == "failed":
                    return self.COLOR_DANGER
                if state == "inactive":
                    return self.COLOR_MUTED
                return self.COLOR_WARNING

            if col == self.COL_ENABLED:
                enabled = service.unit_file_state.lower()
                if enabled == "enabled":
                    return self.COLOR_SUCCESS
                if enabled == "disabled":
                    return self.COLOR_DANGER
                if enabled == "masked":
                    return self.COLOR_BROWN
                return self.COLOR_MUTED

        elif role == Qt.ItemDataRole.FontRole:
            if col in (self.COL_ACTIVE_STATE, self.COL_ENABLED):
                return self._bold_font

        elif role == Qt.ItemDataRole.BackgroundRole:
            highlight = self._highlights.get(service.name)
            if highlight is not None:
                return highlight[1]

        elif role == Qt.ItemDataRole.TextAlignmentRole:
            if col in (self.COL_ACTIVE_STATE, self.COL_SUB_STATE, self.COL_ENABLED):
                return Qt.AlignmentFlag.AlignCenter

        return None

    def headerData(
        self,
        section: int,
        orientation: Qt.Orientation,
        role: int = Qt.ItemDataRole.DisplayRole,
    ) -> Any:
        """Return column header titles."""
        if orientation == Qt.Orientation.Horizontal and role == Qt.ItemDataRole.DisplayRole:
            return self.HEADER_LABELS.get(section)
        return None

    def set_services(self, services: list[Service]) -> None:
        """Populate the model with a new list of services."""
        self.beginResetModel()
        self._services = list(services)
        self._highlights.clear()
        self._reindex()
        self.endResetModel()

    def _reindex(self) -> None:
        self._rows = {service.name: row for row, service in enumerate(self._services)}

    def row_of(self, name: str) -> int | None:
        """Row index of the service called ``name``, or None."""
        return self._rows.get(name)

    def _emit_row_changed(self, row: int) -> None:
        self.dataChanged.emit(self.index(row, 0), self.index(row, self.COL_COUNT - 1))

    def _highlight(self, service: Service) -> None:
        color = self.HIGHLIGHT_FAILED if service.is_failed else self.HIGHLIGHT_CHANGED
        self._highlights[service.name] = (time.monotonic() + self.HIGHLIGHT_SECONDS, color)
        if not self._highlight_timer.isActive():
            self._highlight_timer.start()

    def is_highlighted(self, name: str) -> bool:
        return name in self._highlights

    def apply_service_change(
        self, service: Service, *, highlight: bool = True
    ) -> tuple[Service | None, Service]:
        """Update one service in place (or add it); returns ``(previous, current)``.

        A live event for a unit systemd has unloaded carries no description, so the
        known one is kept. Rows whose state changed are highlighted for a few seconds.
        """
        row = self._rows.get(service.name)
        if row is None:
            self.beginInsertRows(QModelIndex(), len(self._services), len(self._services))
            self._services.append(service)
            self._rows[service.name] = len(self._services) - 1
            self.endInsertRows()
            if highlight:
                self._highlight(service)
                self._emit_row_changed(self._rows[service.name])
            return None, service

        previous = self._services[row]
        if not service.description and previous.description:
            service = dataclasses.replace(service, description=previous.description)
        if service == previous:
            return previous, service
        self._services[row] = service
        if highlight and (
            previous.active_state != service.active_state or previous.sub_state != service.sub_state
        ):
            self._highlight(service)
        self._emit_row_changed(row)
        return previous, service

    def remove_service(self, name: str) -> Service | None:
        """Remove the row for ``name``; returns the removed service, if any."""
        row = self._rows.get(name)
        if row is None:
            return None
        self.beginRemoveRows(QModelIndex(), row, row)
        removed = self._services.pop(row)
        self._highlights.pop(name, None)
        self._reindex()
        self.endRemoveRows()
        return removed

    def merge_services(self, services: list[Service]) -> list[tuple[Service | None, Service]]:
        """Bring the model in line with ``services`` without a reset (keeps selection).

        Returns the ``(previous, current)`` pairs of rows whose content changed.
        """
        wanted = {service.name for service in services}
        for name in [s.name for s in self._services if s.name not in wanted]:
            self.remove_service(name)
        changes: list[tuple[Service | None, Service]] = []
        for service in services:
            previous = self.service_by_name(service.name)
            if previous == service:
                continue
            changes.append(self.apply_service_change(service))
        return changes

    def service_by_name(self, name: str) -> Service | None:
        row = self._rows.get(name)
        return self._services[row] if row is not None else None

    def expire_highlights(self) -> None:
        """Clear highlights whose time is up."""
        now = time.monotonic()
        for name in [n for n, (expiry, _) in self._highlights.items() if expiry <= now]:
            del self._highlights[name]
            row = self._rows.get(name)
            if row is not None:
                self._emit_row_changed(row)
        if not self._highlights:
            self._highlight_timer.stop()

    def service_at(self, row: int) -> Service | None:
        """Return the service at the specified row index, or None if out of bounds."""
        if 0 <= row < len(self._services):
            return self._services[row]
        return None

    def all_services(self) -> list[Service]:
        """Return a copy of the loaded services."""
        return list(self._services)
