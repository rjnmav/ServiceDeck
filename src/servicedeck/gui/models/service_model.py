"""Table model representing systemd services in PySide6."""

from typing import Any, ClassVar

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QPersistentModelIndex, Qt
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

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._services: list[Service] = []
        self._bold_font = QFont()
        self._bold_font.setBold(True)

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
        self.endResetModel()

    def service_at(self, row: int) -> Service | None:
        """Return the service at the specified row index, or None if out of bounds."""
        if 0 <= row < len(self._services):
            return self._services[row]
        return None

    def all_services(self) -> list[Service]:
        """Return a copy of the loaded services."""
        return list(self._services)
