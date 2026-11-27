"""Left navigation sidebar for host switching, scope selection, and quick utilities."""

from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from servicedeck.api_client.models.remote import RemoteDevice
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette


def _status_dot_icon(color_hex: str, size: int = 12) -> QIcon:
    """Create a small crisp status circle icon for remote hosts."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setBrush(QColor(color_hex))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(2, 2, size - 4, size - 4)
    painter.end()
    return QIcon(pixmap)


class HostSidebar(QWidget):
    """Compact left navigation rail for hosts, scope toggle, admin state, and settings."""

    target_host_changed = Signal(object)  # None for local, or device_id (str)
    scope_toggled = Signal(bool)  # True for system, False for user
    add_host_requested = Signal()
    connect_host_requested = Signal(str)
    disconnect_host_requested = Signal(str)
    remove_host_requested = Signal(str)
    drop_admin_requested = Signal()
    reload_daemon_requested = Signal()
    theme_toggle_requested = Signal()
    preferences_requested = Signal()

    def __init__(self, parent: Any = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self.setObjectName("hostSidebar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedWidth(232)

        self._theme = theme
        self._devices: list[RemoteDevice] = []
        self._current_device_id: str | None = None
        self._current_scope = "user"
        self._host_rows: list[QWidget] = []

        self._setup_ui()
        self.refresh_theme(theme)

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 14, 12, 12)
        root.setSpacing(12)

        # ─── Brand Header ───
        brand_row = QHBoxLayout()
        brand_row.setContentsMargins(4, 2, 4, 4)
        brand_row.setSpacing(8)

        self._brand_icon = QLabel(self)
        self._brand_icon.setFixedSize(22, 22)
        logo = QIcon(":/assets/servicedeck.svg")
        if not logo.isNull():
            self._brand_icon.setPixmap(logo.pixmap(22, 22))
        brand_row.addWidget(self._brand_icon)

        brand_title = QLabel("ServiceDeck", self)
        brand_title.setObjectName("brandTitle")
        brand_row.addWidget(brand_title)
        brand_row.addStretch()
        root.addLayout(brand_row)

        # ─── Scope Segmented Toggle ───
        scope_label = QLabel("Scope", self)
        scope_label.setObjectName("sidebarSectionLabel")
        root.addWidget(scope_label)

        scope_box = QWidget(self)
        scope_box.setObjectName("scopeSegmented")
        scope_box.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        scope_layout = QHBoxLayout(scope_box)
        scope_layout.setContentsMargins(3, 3, 3, 3)
        scope_layout.setSpacing(3)

        self._user_scope_btn = QPushButton("User", scope_box)
        self._user_scope_btn.setObjectName("scopeBtn")
        self._user_scope_btn.setCheckable(True)
        self._user_scope_btn.setChecked(True)
        self._user_scope_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._system_scope_btn = QPushButton("System", scope_box)
        self._system_scope_btn.setObjectName("scopeBtn")
        self._system_scope_btn.setCheckable(True)
        self._system_scope_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._scope_group = QButtonGroup(self)
        self._scope_group.setExclusive(True)
        self._scope_group.addButton(self._user_scope_btn, 0)
        self._scope_group.addButton(self._system_scope_btn, 1)
        self._system_scope_btn.toggled.connect(self._on_system_scope_toggled)

        scope_layout.addWidget(self._user_scope_btn)
        scope_layout.addWidget(self._system_scope_btn)
        root.addWidget(scope_box)

        # ─── Admin Session Indicator (shown when remote host is elevated) ───
        self._admin_button = QPushButton("Admin Active  \u2715", self)
        self._admin_button.setObjectName("adminSessionButton")
        self._admin_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._admin_button.setToolTip(
            "System services on this remote host use administrator access.\n"
            "Click to drop administrator privileges."
        )
        self._admin_button.clicked.connect(self.drop_admin_requested.emit)
        self._admin_button.hide()
        root.addWidget(self._admin_button)

        # ─── Hosts Section ───
        hosts_header = QHBoxLayout()
        hosts_header.setContentsMargins(0, 4, 0, 0)
        hosts_label = QLabel("Hosts", self)
        hosts_label.setObjectName("sidebarSectionLabel")
        hosts_header.addWidget(hosts_label)
        hosts_header.addStretch()
        root.addLayout(hosts_header)

        scroll = QScrollArea(self)
        scroll.setObjectName("hostsScroll")
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.viewport().setObjectName("hostsViewport")
        scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        self._hosts_container = QWidget()
        self._hosts_container.setObjectName("hostsContainer")
        self._hosts_container.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._hosts_layout = QVBoxLayout(self._hosts_container)
        self._hosts_layout.setContentsMargins(0, 0, 0, 0)
        self._hosts_layout.setSpacing(3)
        self._hosts_layout.addStretch()
        scroll.setWidget(self._hosts_container)
        root.addWidget(scroll, 1)

        self._add_host_btn = QPushButton("Add Remote Host", self)
        self._add_host_btn.setObjectName("sidebarGhostBtn")
        self._add_host_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_host_btn.setIconSize(QSize(15, 15))
        self._add_host_btn.clicked.connect(self.add_host_requested.emit)
        root.addWidget(self._add_host_btn)

        # ─── Bottom Utility Bar ───
        divider = QFrame(self)
        divider.setFrameShape(QFrame.Shape.HLine)
        divider.setFixedHeight(1)
        divider.setObjectName("sidebarDivider")
        root.addWidget(divider)
        self._divider = divider

        self._reload_daemon_btn = QPushButton("Reload Daemon", self)
        self._reload_daemon_btn.setObjectName("sidebarGhostBtn")
        self._reload_daemon_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reload_daemon_btn.setIconSize(QSize(15, 15))
        self._reload_daemon_btn.setToolTip("Reload systemd daemon unit configuration")
        self._reload_daemon_btn.clicked.connect(self.reload_daemon_requested.emit)
        root.addWidget(self._reload_daemon_btn)

        self._theme_btn = QPushButton("Light Mode", self)
        self._theme_btn.setObjectName("sidebarGhostBtn")
        self._theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_btn.setIconSize(QSize(15, 15))
        self._theme_btn.clicked.connect(self.theme_toggle_requested.emit)
        root.addWidget(self._theme_btn)

        self._prefs_btn = QPushButton("Preferences", self)
        self._prefs_btn.setObjectName("sidebarGhostBtn")
        self._prefs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prefs_btn.setIconSize(QSize(15, 15))
        self._prefs_btn.clicked.connect(self.preferences_requested.emit)
        root.addWidget(self._prefs_btn)

        self._rebuild_hosts()

    @property
    def admin_button(self) -> QPushButton:
        return self._admin_button

    @property
    def system_scope_button(self) -> QPushButton:
        return self._system_scope_btn

    def set_scope(self, scope: str) -> None:
        """Update the segmented scope control without triggering signals."""
        self._current_scope = scope
        self._user_scope_btn.blockSignals(True)
        self._system_scope_btn.blockSignals(True)
        self._system_scope_btn.setChecked(scope == "system")
        self._user_scope_btn.setChecked(scope != "system")
        self._user_scope_btn.blockSignals(False)
        self._system_scope_btn.blockSignals(False)

    def set_scope_enabled(self, enabled: bool) -> None:
        """Enable or disable scope switching during busy loads."""
        self._user_scope_btn.setEnabled(enabled)
        self._system_scope_btn.setEnabled(enabled)

    def set_hosts(self, devices: list[RemoteDevice], current_device_id: str | None = None) -> None:
        """Populate host rows for Local System and configured remote devices."""
        self._devices = list(devices)
        self._current_device_id = current_device_id
        self._rebuild_hosts()

    def _on_system_scope_toggled(self, checked: bool) -> None:
        self._current_scope = "system" if checked else "user"
        self.scope_toggled.emit(checked)

    def _rebuild_hosts(self) -> None:
        for row in self._host_rows:
            self._hosts_layout.removeWidget(row)
            row.hide()
            row.setParent(None)
            row.deleteLater()
        self._host_rows.clear()

        palette = get_palette(self._theme)
        # Insert rows before the trailing stretch
        insert_idx = 0

        # Local System row
        local_row = self._make_host_row(
            device_id=None,
            label="Local System",
            tooltip="Manage systemd units on this local machine",
            icon=IconHelper.svg_icon(
                "monitor",
                palette.accent if self._current_device_id is None else palette.text_secondary,
            ),
            is_active=(self._current_device_id is None),
            device=None,
        )
        self._hosts_layout.insertWidget(insert_idx, local_row)
        self._host_rows.append(local_row)
        insert_idx += 1

        for dev in self._devices:
            is_active = self._current_device_id == dev.id
            dot_color = palette.success_text if dev.connected else palette.muted_text
            status_word = "Connected" if dev.connected else "Offline"
            row = self._make_host_row(
                device_id=dev.id,
                label=dev.display_name,
                tooltip=f"{dev.hostname}:{dev.port} ({status_word})",
                icon=_status_dot_icon(dot_color),
                is_active=is_active,
                device=dev,
            )
            self._hosts_layout.insertWidget(insert_idx, row)
            self._host_rows.append(row)
            insert_idx += 1

    def _make_host_row(
        self,
        *,
        device_id: str | None,
        label: str,
        tooltip: str,
        icon: QIcon,
        is_active: bool,
        device: RemoteDevice | None,
    ) -> QWidget:
        palette = get_palette(self._theme)
        row = QWidget(self._hosts_container)
        row.setObjectName("hostItemRow")
        row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        row.setProperty("active", "true" if is_active else "false")

        layout = QHBoxLayout(row)
        layout.setContentsMargins(2, 1, 2, 1)
        layout.setSpacing(2)

        select_btn = QPushButton(label, row)
        select_btn.setObjectName("hostRowSelectBtn")
        select_btn.setProperty("active", "true" if is_active else "false")
        select_btn.setIcon(icon)
        select_btn.setIconSize(QSize(15, 15))
        select_btn.setToolTip(tooltip)
        select_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        select_btn.clicked.connect(lambda _checked=False, did=device_id: self._select_host(did))
        layout.addWidget(select_btn, 1)

        if device is not None:
            menu_btn = QPushButton(row)
            menu_btn.setObjectName("hostRowMenuBtn")
            menu_btn.setIcon(IconHelper.svg_icon("more", palette.text_secondary))
            menu_btn.setIconSize(QSize(14, 14))
            menu_btn.setToolTip("Host actions")
            menu_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            menu_btn.clicked.connect(
                lambda _checked=False, d=device, btn=menu_btn: self._open_host_menu(d, btn)
            )
            layout.addWidget(menu_btn)

        return row

    def _select_host(self, device_id: str | None) -> None:
        if device_id == self._current_device_id:
            return
        self._current_device_id = device_id
        self._rebuild_hosts()
        self.target_host_changed.emit(device_id)

    def _open_host_menu(self, device: RemoteDevice, anchor: QPushButton) -> None:
        menu = QMenu(self)
        if device.connected:
            menu.addAction(
                "Disconnect",
                lambda: self.disconnect_host_requested.emit(device.id),
            )
        else:
            menu.addAction(
                "Connect",
                lambda: self.connect_host_requested.emit(device.id),
            )
        menu.addSeparator()
        menu.addAction(
            "Remove Host",
            lambda: self.remove_host_requested.emit(device.id),
        )
        pos = anchor.mapToGlobal(anchor.rect().bottomLeft())
        menu.exec(pos)

    def refresh_theme(self, theme: str) -> None:
        """Update icons and inline borders for the active theme."""
        self._theme = theme
        palette = get_palette(theme)

        self._divider.setStyleSheet(f"background-color: {palette.border}; border: none;")
        self._add_host_btn.setIcon(IconHelper.svg_icon("plus", palette.text_secondary))
        self._reload_daemon_btn.setIcon(IconHelper.svg_icon("restart", palette.text_secondary))
        self._prefs_btn.setIcon(IconHelper.svg_icon("settings", palette.text_secondary))
        self._admin_button.setIcon(IconHelper.svg_icon("shield", palette.warning_text))

        if palette.is_dark:
            self._theme_btn.setText("Light Mode")
            self._theme_btn.setIcon(IconHelper.svg_icon("sun", palette.text_secondary))
        else:
            self._theme_btn.setText("Dark Mode")
            self._theme_btn.setIcon(IconHelper.svg_icon("moon", palette.text_secondary))

        self._rebuild_hosts()
