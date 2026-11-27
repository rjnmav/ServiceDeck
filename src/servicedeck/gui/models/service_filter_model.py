"""Sort and filter proxy model for systemd services."""

from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QSortFilterProxyModel, Qt

from servicedeck.gui.models.service_model import ServiceTableModel

_DEFAULT_INDEX = QModelIndex()


class ServiceFilterModel(QSortFilterProxyModel):
    """Proxy model filtering services by name/description and active state."""

    def __init__(self, parent: Any = None) -> None:
        super().__init__(parent)
        self._name_filter = ""
        self._active_state_filter = ""

        self.setDynamicSortFilter(True)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortRole(Qt.ItemDataRole.DisplayRole)

    def set_name_filter(self, text: str) -> None:
        """Filter services whose name or description contains the given substring."""
        self._name_filter = text.strip().lower()
        self.invalidate()

    def set_active_state_filter(self, state: str) -> None:
        """Filter services by active state ('active', 'inactive', 'failed', or '' for all)."""
        self._active_state_filter = state.strip().lower()
        self.invalidate()

    def filterAcceptsRow(
        self,
        source_row: int,
        source_parent: QModelIndex | QPersistentModelIndex = _DEFAULT_INDEX,
    ) -> bool:
        """Evaluate if the row satisfies both text and active state filters."""
        source_model = self.sourceModel()
        if source_model is None:
            return True

        service_index = source_model.index(source_row, ServiceTableModel.COL_SERVICE, source_parent)
        name = str(source_model.data(service_index, Qt.ItemDataRole.DisplayRole) or "").lower()
        desc = str(
            source_model.data(service_index, ServiceTableModel.ROLE_DESCRIPTION) or ""
        ).lower()
        active_state = str(
            source_model.data(service_index, ServiceTableModel.ROLE_ACTIVE_STATE) or ""
        ).lower()

        if self._name_filter and (self._name_filter not in name and self._name_filter not in desc):
            return False

        if self._active_state_filter and active_state != self._active_state_filter:
            return False

        return True
