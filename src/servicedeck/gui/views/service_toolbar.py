"""Workspace header bar with context title, live status badge, search, and filter chips."""

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QButtonGroup,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette


class ServiceToolbar(QWidget):
    """Clean two-row header containing context, primary CTAs, search, and status filter chips."""

    search_text_changed = Signal(str)
    active_state_filter_changed = Signal(str)
    refresh_requested = Signal()
    create_requested = Signal()

    def __init__(self, parent: Any = None, is_dark: bool = True) -> None:
        super().__init__(parent)
        self.setObjectName("workspaceHeader")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._is_dark = is_dark
        self._refresh_action = QAction("Refresh", self)
        self._create_action = QAction("New Service", self)
        self._refresh_action.triggered.connect(self.refresh_requested.emit)
        self._create_action.triggered.connect(self.create_requested.emit)

        self._setup_ui()
        self.refresh_icons(is_dark=is_dark)

    @property
    def refresh_action(self) -> QAction:
        return self._refresh_action

    @property
    def create_action(self) -> QAction:
        return self._create_action

    @property
    def search_edit(self) -> QLineEdit:
        return self._search_edit

    @property
    def live_label(self) -> QLabel:
        return self._live_label

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 14, 20, 12)
        layout.setSpacing(12)

        # ─── Row 1: Context Title + Live Badge + Global CTAs ───
        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(2)

        title_line = QHBoxLayout()
        title_line.setSpacing(10)

        self._context_title = QLabel("Local System", self)
        self._context_title.setObjectName("contextTitle")
        title_line.addWidget(self._context_title)

        self._live_label = QLabel("○ Offline", self)
        self._live_label.setObjectName("liveIndicator")
        title_line.addWidget(self._live_label)
        title_line.addStretch()

        title_col.addLayout(title_line)

        self._context_subtitle = QLabel("User Services", self)
        self._context_subtitle.setObjectName("contextSubtitle")
        title_col.addWidget(self._context_subtitle)

        top_row.addLayout(title_col, 1)

        self._refresh_btn = QPushButton("Refresh", self)
        self._refresh_btn.setObjectName("iconBtn")
        self._refresh_btn.setIconSize(QSize(15, 15))
        self._refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._refresh_btn.setToolTip("Refresh service list (F5)")
        self._refresh_btn.clicked.connect(self._refresh_action.trigger)
        top_row.addWidget(self._refresh_btn)

        self._create_btn = QPushButton("New Service", self)
        self._create_btn.setObjectName("primary")
        self._create_btn.setIconSize(QSize(15, 15))
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.setToolTip("Create a new systemd service unit")
        self._create_btn.clicked.connect(self._create_action.trigger)
        top_row.addWidget(self._create_btn)

        layout.addLayout(top_row)

        # ─── Row 2: Search Input + Summary Filter Chips ───
        filter_row = QHBoxLayout()
        filter_row.setSpacing(10)

        self._search_edit = QLineEdit(self)
        self._search_edit.setObjectName("searchEdit")
        self._search_edit.setPlaceholderText("Search services by name or description... (Ctrl+F)")
        self._search_edit.setClearButtonEnabled(True)
        self._search_edit.setMinimumWidth(240)
        self._search_edit.textChanged.connect(self.search_text_changed.emit)
        filter_row.addWidget(self._search_edit, 1)

        self._chip_group = QButtonGroup(self)
        self._chip_group.setExclusive(True)

        self._chips: dict[str, QPushButton] = {}
        chip_specs = [
            ("", "All", "filterChip"),
            ("active", "Active", "filterChip"),
            ("failed", "Failed", "filterChipFailed"),
            ("inactive", "Inactive", "filterChip"),
        ]
        for state_key, label, obj_name in chip_specs:
            chip = QPushButton(label, self)
            chip.setObjectName(obj_name)
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            if state_key == "":
                chip.setChecked(True)
            chip.clicked.connect(
                lambda _checked=False, sk=state_key: self.active_state_filter_changed.emit(sk)
            )
            self._chip_group.addButton(chip)
            self._chips[state_key] = chip
            filter_row.addWidget(chip)

        layout.addLayout(filter_row)

    def set_context(self, host_label: str, scope: str) -> None:
        """Update context header text."""
        self._context_title.setText(host_label)
        scope_text = "System Services" if scope == "system" else "User Services"
        self._context_subtitle.setText(scope_text)

    def update_counts(self, counts: dict[str, int]) -> None:
        """Update the live count badges on the status filter chips."""
        self._chips[""].setText(f"All  {counts.get('all', 0)}")
        self._chips["active"].setText(f"Active  {counts.get('active', 0)}")
        self._chips["failed"].setText(f"Failed  {counts.get('failed', 0)}")
        self._chips["inactive"].setText(f"Inactive  {counts.get('inactive', 0)}")

    def set_live_status(self, connected: bool, tooltip: str) -> None:
        """Update the header live connection badge."""
        palette = get_palette("dark" if self._is_dark else "light")
        self._live_label.setText("● Live" if connected else "○ Reconnecting")
        color = palette.success_text if connected else palette.muted_text
        self._live_label.setStyleSheet(f"color: {color};")
        self._live_label.setToolTip(tooltip)

    def focus_search(self) -> None:
        """Focus the search field and select its text."""
        self._search_edit.setFocus()
        self._search_edit.selectAll()

    def refresh_icons(self, is_dark: bool) -> None:
        """Refresh button icons to match the active theme."""
        self._is_dark = is_dark
        palette = get_palette("dark" if is_dark else "light")
        self._refresh_btn.setIcon(IconHelper.svg_icon("refresh", palette.text_primary))
        self._create_btn.setIcon(IconHelper.svg_icon("plus", palette.on_accent))


ServiceHeaderBar = ServiceToolbar
