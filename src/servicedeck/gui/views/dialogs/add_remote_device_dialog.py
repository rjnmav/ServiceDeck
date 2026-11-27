"""Dialog for adding a new remote Linux host connection in ServiceDeck."""

import re
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.remote import KeySetupInfo, RemoteConnectionInfo, RemoteDevice
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette
from servicedeck.gui.views.dialogs.remote_onboarding import connect_with_onboarding
from servicedeck.gui.workers.service_worker import run_async_task

#: (label, agent_mode) choices; the first is the default.
AGENT_MODES = (
    ("Bundled (nothing installed remotely)", "bundled"),
    ("Installed servicedeck-remote", "installed"),
    ("Auto (prefer installed)", "auto"),
)


class AddRemoteDeviceDialog(QDialog):
    """Modal dialog to register a remote Linux machine for SSH management."""

    def __init__(self, parent: Any = None, client: ServiceDeckClient | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Remote Linux Host")
        self.setMinimumWidth(540)
        self.setObjectName("addRemoteDeviceDialog")
        self._client = client
        self.created_device: RemoteDevice | None = None
        self._theme = getattr(parent, "_current_theme", "dark")

        self._setup_ui()

    def _setup_ui(self) -> None:
        palette = get_palette(self._theme)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─── Header Band ───
        header = QWidget(self)
        header.setObjectName("dialogHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        header_layout.setSpacing(12)

        icon_lbl = QLabel(header)
        icon_lbl.setPixmap(IconHelper.svg_icon("server", palette.accent).pixmap(QSize(24, 24)))
        header_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title_label = QLabel("Add Remote Linux Host", header)
        title_label.setObjectName("contextTitle")

        subtitle_label = QLabel(
            "Connect over SSH to monitor and manage remote systemd services.",
            header,
        )
        subtitle_label.setObjectName("contextSubtitle")
        subtitle_label.setWordWrap(True)

        header_text.addWidget(title_label)
        header_text.addWidget(subtitle_label)
        header_layout.addLayout(header_text, 1)
        root.addWidget(header)

        # ─── Body ───
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 14)
        body_layout.setSpacing(12)

        # Connection Card
        conn_card = QFrame(body)
        conn_card.setObjectName("dialogCard")
        conn_layout = QVBoxLayout(conn_card)
        conn_layout.setContentsMargins(16, 14, 16, 14)
        conn_layout.setSpacing(10)

        form_layout = QFormLayout()
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def lock_height(widget: QWidget) -> None:
            widget.setFixedHeight(36)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._host_edit = QLineEdit(conn_card)
        self._host_edit.setPlaceholderText("e.g. 192.168.1.50 or server.local")
        lock_height(self._host_edit)
        self._host_edit.textChanged.connect(self._on_host_text_changed)
        form_layout.addRow("Host / IP *:", self._host_edit)

        self._name_edit = QLineEdit(conn_card)
        self._name_edit.setPlaceholderText("e.g. Primary Web Server")
        lock_height(self._name_edit)
        form_layout.addRow("Display Name:", self._name_edit)

        user_port_row = QHBoxLayout()
        user_port_row.setSpacing(10)
        self._user_edit = QLineEdit(conn_card)
        self._user_edit.setPlaceholderText("Defaults to current user")
        lock_height(self._user_edit)
        user_port_row.addWidget(self._user_edit, 1)

        port_lbl = QLabel("Port:", conn_card)
        self._port_spin = QSpinBox(conn_card)
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(22)
        self._port_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self._port_spin.setFixedSize(76, 36)
        user_port_row.addWidget(port_lbl)
        user_port_row.addWidget(self._port_spin)
        form_layout.addRow("SSH User:", user_port_row)

        conn_layout.addLayout(form_layout)
        body_layout.addWidget(conn_card)

        # Progressive Disclosure: Advanced Options
        self._adv_toggle = QPushButton("▸ Advanced SSH && Agent Options", body)
        self._adv_toggle.setObjectName("sidebarGhostBtn")
        self._adv_toggle.setCheckable(True)
        self._adv_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._adv_toggle.toggled.connect(self._on_toggle_advanced)
        body_layout.addWidget(self._adv_toggle)

        self._adv_section = QFrame(body)
        self._adv_section.setObjectName("dialogCard")
        adv_form = QFormLayout(self._adv_section)
        adv_form.setContentsMargins(16, 14, 16, 14)
        adv_form.setSpacing(12)
        adv_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        key_layout = QHBoxLayout()
        key_layout.setSpacing(8)
        self._key_edit = QLineEdit(self._adv_section)
        self._key_edit.setPlaceholderText("Optional (leave blank for ssh-agent)")
        lock_height(self._key_edit)
        key_browse_btn = QPushButton("Browse...", self._adv_section)
        key_browse_btn.setFixedHeight(36)
        key_browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        key_browse_btn.clicked.connect(self._on_browse_key_clicked)
        key_layout.addWidget(self._key_edit, 1)
        key_layout.addWidget(key_browse_btn)
        adv_form.addRow("Private Key:", key_layout)

        self._agent_mode_combo = QComboBox(self._adv_section)
        lock_height(self._agent_mode_combo)
        for label, mode in AGENT_MODES:
            self._agent_mode_combo.addItem(label, mode)
        self._agent_mode_combo.setToolTip(
            "Bundled: ServiceDeck sends its agent over SSH; nothing is installed remotely.\n"
            "Installed: run servicedeck-remote already installed on the host.\n"
            "Auto: use the installed agent when present, otherwise the bundled one."
        )
        adv_form.addRow("Agent Mode:", self._agent_mode_combo)

        self._adv_section.hide()
        body_layout.addWidget(self._adv_section)

        # Reserved non-shifting alert slot (prevents layout jump when errors appear)
        self._banner_stack = QStackedWidget(body)
        self._banner_stack.setFixedHeight(42)

        idle_slot = QWidget(self._banner_stack)
        self._banner_stack.addWidget(idle_slot)

        self._status_banner = QLabel("", self._banner_stack)
        self._status_banner.setObjectName("dialogBanner")
        self._status_banner.setWordWrap(True)
        self._status_banner.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._banner_stack.addWidget(self._status_banner)
        self._banner_stack.setCurrentIndex(0)

        body_layout.addWidget(self._banner_stack)
        root.addWidget(body, 1)

        # ─── Footer Band ───
        footer = QWidget(self)
        footer.setObjectName("dialogFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        btn_layout = QHBoxLayout(footer)
        btn_layout.setContentsMargins(24, 14, 24, 14)
        btn_layout.setSpacing(10)

        self._test_btn = QPushButton("Test Connection", footer)
        self._test_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._test_btn.clicked.connect(self._on_test_connection_clicked)
        btn_layout.addWidget(self._test_btn)

        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel", footer)
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Add && Connect", footer)
        self._save_btn.setObjectName("primary")
        self._save_btn.setDefault(True)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self._save_btn)

        root.addWidget(footer)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

    def _on_toggle_advanced(self, expanded: bool) -> None:
        self._adv_section.setVisible(expanded)
        self._adv_toggle.setText(
            "▾ Advanced SSH && Agent Options" if expanded else "▸ Advanced SSH && Agent Options"
        )
        self.setMinimumHeight(0)
        self.setMaximumHeight(16777215)
        self.adjustSize()
        self.setFixedHeight(self.sizeHint().height())

    def _set_host_invalid(self, invalid: bool) -> None:
        self._host_edit.setProperty("invalid", "true" if invalid else "false")
        self._host_edit.style().unpolish(self._host_edit)
        self._host_edit.style().polish(self._host_edit)

    def _on_host_text_changed(self, text: str) -> None:
        """Auto-populate display name placeholder from hostname and clear error state."""
        if text.strip():
            self._set_host_invalid(False)
            if self._status_banner.property("state") == "error":
                self._clear_banner()
        if (
            not self._name_edit.text()
            or self._name_edit.text() == self._host_edit.placeholderText()
        ):
            clean = text.strip()
            if clean:
                self._name_edit.setPlaceholderText(clean)

    def _on_browse_key_clicked(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select SSH Private Key",
            "",
            "All Files (*);;SSH Keys (id_*);;PEM Files (*.pem)",
        )
        if file_path:
            self._key_edit.setText(file_path)

    def _generate_device_id(self, host: str) -> str:
        """Create a clean device slug from hostname."""
        slug = re.sub(r"[^a-zA-Z0-9_-]", "-", host.strip().lower())
        return slug.strip("-") or "remote-host"

    def _clear_banner(self) -> None:
        self._status_banner.setText("")
        self._status_banner.setProperty("state", "idle")
        self._banner_stack.setCurrentIndex(0)

    def _show_banner(
        self, message: str, is_error: bool = False, *, state: str | None = None
    ) -> None:
        resolved_state = state or ("error" if is_error else "success")
        self._status_banner.setText(message)
        self._status_banner.setProperty("state", resolved_state)
        self._status_banner.style().unpolish(self._status_banner)
        self._status_banner.style().polish(self._status_banner)
        self._banner_stack.setCurrentIndex(1)

    def _on_test_connection_clicked(self) -> None:
        """Test SSH connectivity and servicedeck-remote presence before adding."""
        host = self._host_edit.text().strip()
        if not host:
            self._set_host_invalid(True)
            self._host_edit.setFocus()
            self._show_banner("Please enter a valid Host / IP address first.", is_error=True)
            return

        if not self._client:
            self._show_banner("API Client is not available.", is_error=True)
            return

        port = self._port_spin.value()
        user = self._user_edit.text().strip() or None
        key = self._key_edit.text().strip() or None
        dev_id = f"test-{self._generate_device_id(host)}"

        self._test_btn.setEnabled(False)
        self._show_banner("Testing SSH connection and agent handshake...", state="info")

        target = f"{user}@{host}" if user else host

        def cleanup() -> None:
            def remove() -> None:
                try:
                    self._client.remove_device(dev_id)
                except Exception:
                    pass

            run_async_task(remove)

        def on_success(info: RemoteConnectionInfo) -> None:
            cleanup()
            self._test_btn.setEnabled(True)
            user_str = info.remote_user or "user"
            uid_str = f"UID {info.remote_uid}" if info.remote_uid is not None else ""
            ver_str = f"v{info.remote_version}" if info.remote_version else ""
            msg = (
                f"Connection successful: {info.remote_host} ({user_str} {uid_str}) {ver_str}"
            ).strip()
            self._show_banner(msg, is_error=False)

        def on_error(msg: str, exc: Any) -> None:
            cleanup()
            self._test_btn.setEnabled(True)
            self._show_banner(f"Connection failed: {msg}", is_error=True)

        def on_registered(_dev: RemoteDevice) -> None:
            connect_with_onboarding(
                self,
                self._client,
                dev_id,
                target=target,
                on_success=on_success,
                on_error=on_error,
                on_key_installed=self._on_key_installed,
            )

        run_async_task(
            self._client.add_device,
            id=dev_id,
            hostname=host,
            port=port,
            username=user,
            ssh_key_path=key,
            agent_mode=self._agent_mode_combo.currentData(),
            on_success=on_registered,
            on_error=on_error,
        )

    def _on_key_installed(self, result: KeySetupInfo) -> None:
        """Remember the installed key so saving the device keeps using it."""
        self._key_edit.setText(result.key_path)
        self._show_banner(
            f"SSH key installed ({result.key_fingerprint}). Connecting...", state="info"
        )

    def _on_save_clicked(self) -> None:
        """Save device configuration and accept dialog."""
        host = self._host_edit.text().strip()
        if not host:
            self._set_host_invalid(True)
            self._host_edit.setFocus()
            self._show_banner("Please enter a valid Host / IP address first.", is_error=True)
            return

        if not self._client:
            self._show_banner("API client unavailable.", is_error=True)
            return

        name = self._name_edit.text().strip() or self._name_edit.placeholderText() or host
        user = self._user_edit.text().strip() or None
        port = self._port_spin.value()
        key = self._key_edit.text().strip() or None
        dev_id = self._generate_device_id(host)

        self._save_btn.setEnabled(False)
        self._show_banner("Registering device...", state="info")

        target = f"{user}@{host}" if user else host

        def on_register_error(msg: str, exc: Any) -> None:
            self._save_btn.setEnabled(True)
            self._show_banner(f"Failed to add device: {msg}", is_error=True)

        def on_registered(dev: RemoteDevice) -> None:
            self.created_device = dev
            self._show_banner("Device saved. Connecting...", state="info")

            def on_connected(_info: RemoteConnectionInfo) -> None:
                self.accept()

            def on_connect_error(msg: str, exc: Any) -> None:
                QMessageBox.warning(
                    self,
                    "Device Saved",
                    f"The device was saved, but connecting to it failed:\n\n{msg}\n\n"
                    "You can connect again later from the host menu in the sidebar.",
                )
                self.accept()

            connect_with_onboarding(
                self,
                self._client,
                dev.id,
                target=target,
                on_success=on_connected,
                on_error=on_connect_error,
                on_key_installed=self._on_key_installed,
            )

        run_async_task(
            self._client.add_device,
            id=dev_id,
            hostname=host,
            port=port,
            username=user,
            display_name=name,
            ssh_key_path=key,
            agent_mode=self._agent_mode_combo.currentData(),
            on_success=on_registered,
            on_error=on_register_error,
        )
