"""Toolbar widget containing service lifecycle controls, search, and scope toggle."""

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QLabel,
    QLineEdit,
    QSizePolicy,
    QToolBar,
    QWidget,
)

from servicedeck.gui.resources.icon_helper import IconHelper


class ServiceToolbar(QToolBar):
    """Toolbar providing actions for starting, stopping, filtering, and switching service scope."""

    search_text_changed = Signal(str)
    active_state_filter_changed = Signal(str)
    system_mode_toggled = Signal(bool)

    def __init__(self, parent: Any = None, is_dark: bool = True) -> None:
        super().__init__("Service Actions", parent)
        self.setObjectName("serviceToolbar")
        self.setMovable(False)
        self.setIconSize(QSize(20, 20))
        self.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        self._is_dark = is_dark

        self._setup_actions()
        self.addSeparator()
        self._setup_search_and_filters()
        self.refresh_icons(is_dark=self._is_dark)

    @property
    def start_action(self) -> QAction:
        return self._start_action

    @property
    def stop_action(self) -> QAction:
        return self._stop_action

    @property
    def restart_action(self) -> QAction:
        return self._restart_action

    @property
    def enable_action(self) -> QAction:
        return self._enable_action

    @property
    def disable_action(self) -> QAction:
        return self._disable_action

    @property
    def mask_action(self) -> QAction:
        return self._mask_action

    @property
    def unmask_action(self) -> QAction:
        return self._unmask_action

    @property
    def reload_action(self) -> QAction:
        return self._reload_action

    @property
    def refresh_action(self) -> QAction:
        return self._refresh_action

    @property
    def create_action(self) -> QAction:
        return self._create_action

    @property
    def system_toggle(self) -> QCheckBox:
        return self._system_toggle

    def _setup_actions(self) -> None:
        self._start_action = self.addAction("Start")
        self._stop_action = self.addAction("Stop")
        self._restart_action = self.addAction("Restart")

        self.addSeparator()

        self._enable_action = self.addAction("Enable")
        self._disable_action = self.addAction("Disable")

        self.addSeparator()

        self._mask_action = self.addAction("Mask")
        self._unmask_action = self.addAction("Unmask")

        self.addSeparator()

        self._reload_action = self.addAction("Reload Daemon")
        self._refresh_action = self.addAction("Refresh")
        self._create_action = self.addAction("Create Service")

        self._start_action.setToolTip("Start the selected service")
        self._stop_action.setToolTip("Stop the selected service")
        self._restart_action.setToolTip("Restart the selected service")
        self._enable_action.setToolTip("Enable the selected service at boot")
        self._disable_action.setToolTip("Disable the selected service at boot")
        self._mask_action.setToolTip("Mask the selected service (prevent starting)")
        self._unmask_action.setToolTip("Unmask the selected service")
        self._reload_action.setToolTip("Reload systemd daemon configuration")
        self._refresh_action.setToolTip("Refresh the service list")
        self._create_action.setToolTip("Create a new systemd service unit")

        self.set_actions_enabled(False)

    def _setup_search_and_filters(self) -> None:
        # Search label & input
        search_label = QLabel("Search: ", self)
        self.addWidget(search_label)

        self._search_edit = QLineEdit(self)
        self._search_edit.setObjectName("searchEdit")
        self._search_edit.setPlaceholderText("Filter by name...")
        self._search_edit.setMinimumWidth(200)
        self._search_edit.setMaximumWidth(300)
        self._search_edit.setClearButtonEnabled(True)
        self.addWidget(self._search_edit)

        spacer = QWidget()
        spacer.setFixedWidth(10)
        spacer.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.addWidget(spacer)

        self._search_edit.textChanged.connect(self.search_text_changed.emit)

        # Status filter label & combo
        filter_label = QLabel("Status: ", self)
        self.addWidget(filter_label)

        self._filter_combo = QComboBox(self)
        self._filter_combo.setObjectName("filterCombo")
        self._filter_combo.addItem("All", "")
        self._filter_combo.addItem("Active", "active")
        self._filter_combo.addItem("Inactive", "inactive")
        self._filter_combo.addItem("Failed", "failed")
        self._filter_combo.setMinimumWidth(100)
        self._filter_combo.setMaximumWidth(200)
        self._filter_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        self.addWidget(self._filter_combo)

        self._filter_combo.currentIndexChanged.connect(self._on_filter_changed)

        self.addSeparator()

        # Scope checkbox (unchecked = user, checked = system)
        self._system_toggle = QCheckBox("System Services", self)
        self._system_toggle.setObjectName("systemToggle")
        self.addWidget(self._system_toggle)

        self._system_toggle.toggled.connect(self.system_mode_toggled.emit)

    def _on_filter_changed(self, index: int) -> None:
        state_data = self._filter_combo.itemData(index) or ""
        self.active_state_filter_changed.emit(str(state_data))

    def set_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable row-specific actions (start, stop, restart, enable, disable)."""
        self._start_action.setEnabled(enabled)
        self._stop_action.setEnabled(enabled)
        self._restart_action.setEnabled(enabled)
        self._enable_action.setEnabled(enabled)
        self._disable_action.setEnabled(enabled)
        self._mask_action.setEnabled(enabled)
        self._unmask_action.setEnabled(enabled)

    def refresh_icons(self, is_dark: bool = True) -> None:
        """Refresh action icons according to active light/dark theme."""
        self._is_dark = is_dark
        neutral_color = QColor("#e5e9f0") if is_dark else QColor("#2d3748")
        success_color = QColor("#81C784") if is_dark else QColor("#2E7D32")
        danger_color = QColor("#E57373") if is_dark else QColor("#C62828")

        self._start_action.setIcon(IconHelper.tinted_icon("media-playback-start", success_color))
        self._stop_action.setIcon(IconHelper.tinted_icon("media-playback-stop", danger_color))
        self._restart_action.setIcon(IconHelper.tinted_icon("view-refresh", neutral_color))
        self._enable_action.setIcon(IconHelper.tinted_icon("emblem-default", success_color))
        self._disable_action.setIcon(IconHelper.tinted_icon("process-stop", danger_color))
        self._mask_action.setIcon(IconHelper.tinted_icon("object-locked", danger_color))
        self._unmask_action.setIcon(IconHelper.tinted_icon("object-unlocked", neutral_color))
        self._reload_action.setIcon(IconHelper.tinted_icon("view-refresh", neutral_color))
        self._refresh_action.setIcon(IconHelper.tinted_icon("view-refresh", neutral_color))
        self._create_action.setIcon(IconHelper.tinted_icon("document-new", neutral_color))
