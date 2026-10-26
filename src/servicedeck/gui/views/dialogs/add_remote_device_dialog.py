"""Dialog for adding a new remote Linux host connection in ServiceDeck."""

import re
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.remote import RemoteConnectionInfo, RemoteDevice
from servicedeck.gui.workers.service_worker import run_async_task


class AddRemoteDeviceDialog(QDialog):
    """Frictionless modal dialog to register a remote Linux machine for SSH management."""

    def __init__(self, parent: Any = None, client: ServiceDeckClient | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Remote Linux Host")
        self.setMinimumSize(540, 420)
        self.setObjectName("addRemoteDeviceDialog")
        self._client = client
        self.created_device: RemoteDevice | None = None

        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # ─── Header ───
        header_layout = QVBoxLayout()
        title_label = QLabel("Add Remote Linux Host", self)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("dialogTitle")

        subtitle_label = QLabel(
            "Connect over secure SSH to monitor and manage remote systemd services.", self
        )
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setStyleSheet("color: #a0a0a0;")

        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        layout.addLayout(header_layout)

        # ─── Form ───
        form_layout = QFormLayout()
        form_layout.setSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # Host / IP
        self._host_edit = QLineEdit(self)
        self._host_edit.setPlaceholderText("e.g. 192.168.1.50 or server.local")
        self._host_edit.textChanged.connect(self._on_host_text_changed)
        form_layout.addRow("Host / IP *:", self._host_edit)

        # Friendly Display Name
        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("e.g. Primary Web Server")
        form_layout.addRow("Display Name:", self._name_edit)

        # Username
        self._user_edit = QLineEdit(self)
        self._user_edit.setPlaceholderText("Defaults to your local user if empty")
        form_layout.addRow("SSH User:", self._user_edit)

        # Port
        self._port_spin = QSpinBox(self)
        self._port_spin.setRange(1, 65535)
        self._port_spin.setValue(22)
        self._port_spin.setFixedWidth(100)
        form_layout.addRow("SSH Port:", self._port_spin)

        # Private Key Path
        key_layout = QHBoxLayout()
        self._key_edit = QLineEdit(self)
        self._key_edit.setPlaceholderText("Optional (leave blank to use standard ssh-agent)")
        key_browse_btn = QPushButton("Browse...", self)
        key_browse_btn.setFixedWidth(90)
        key_browse_btn.clicked.connect(self._on_browse_key_clicked)
        key_layout.addWidget(self._key_edit)
        key_layout.addWidget(key_browse_btn)
        form_layout.addRow("Private Key:", key_layout)

        layout.addLayout(form_layout)

        # ─── Status / Test Banner ───
        self._status_banner = QLabel("", self)
        self._status_banner.setWordWrap(True)
        self._status_banner.setStyleSheet("padding: 6px 10px; border-radius: 6px;")
        self._status_banner.hide()
        layout.addWidget(self._status_banner)

        layout.addStretch()

        # ─── Button Bar ───
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self._test_btn = QPushButton("Test Connection", self)
        self._test_btn.clicked.connect(self._on_test_connection_clicked)
        btn_layout.addWidget(self._test_btn)

        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel", self)
        self._cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self._cancel_btn)

        self._save_btn = QPushButton("Add & Connect", self)
        self._save_btn.setDefault(True)
        self._save_btn.setStyleSheet(
            "background-color: #2b8a3e; color: #ffffff; font-weight: bold; padding: 6px 16px; border-radius: 6px;"
        )
        self._save_btn.clicked.connect(self._on_save_clicked)
        btn_layout.addWidget(self._save_btn)

        layout.addLayout(btn_layout)

    def _on_host_text_changed(self, text: str) -> None:
        """Auto-populate display name from hostname if name edit is untouched."""
        if not self._name_edit.text() or self._name_edit.text() == self._host_edit.placeholderText():
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

    def _show_banner(self, message: str, is_error: bool = False) -> None:
        self._status_banner.setText(message)
        if is_error:
            self._status_banner.setStyleSheet(
                "background-color: #442726; color: #ff8787; border: 1px solid #c92a2a; padding: 6px 10px; border-radius: 6px;"
            )
        else:
            self._status_banner.setStyleSheet(
                "background-color: #1b382b; color: #69db7c; border: 1px solid #2b8a3e; padding: 6px 10px; border-radius: 6px;"
            )
        self._status_banner.show()

    def _on_test_connection_clicked(self) -> None:
        """Test SSH connectivity and servicedeck-remote presence before adding."""
        host = self._host_edit.text().strip()
        if not host:
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
        self._show_banner("Testing SSH connection and agent handshake...", is_error=False)

        def task() -> RemoteConnectionInfo:
            # Register temporary device, connect, and remove
            self._client.add_device(
                id=dev_id,
                hostname=host,
                port=port,
                username=user,
                ssh_key_path=key,
            )
            try:
                info = self._client.connect_device(dev_id)
                return info
            finally:
                try:
                    self._client.remove_device(dev_id)
                except Exception:
                    pass

        def on_success(info: RemoteConnectionInfo) -> None:
            self._test_btn.setEnabled(True)
            user_str = info.remote_user or "user"
            uid_str = f"UID {info.remote_uid}" if info.remote_uid is not None else ""
            ver_str = f"v{info.remote_version}" if info.remote_version else ""
            msg = f"✔ Connection successful! Remote host: {info.remote_host} ({user_str} {uid_str}) {ver_str}"
            self._show_banner(msg, is_error=False)

        def on_error(msg: str, exc: Any) -> None:
            self._test_btn.setEnabled(True)
            self._show_banner(f"✖ Connection failed: {msg}", is_error=True)

        run_async_task(task, on_success=on_success, on_error=on_error)

    def _on_save_clicked(self) -> None:
        """Save device configuration and accept dialog."""
        host = self._host_edit.text().strip()
        if not host:
            QMessageBox.warning(self, "Missing Host", "Please enter a valid Host / IP address.")
            self._host_edit.setFocus()
            return

        if not self._client:
            QMessageBox.critical(self, "Error", "API client unavailable.")
            return

        name = self._name_edit.text().strip() or self._name_edit.placeholderText() or host
        user = self._user_edit.text().strip() or None
        port = self._port_spin.value()
        key = self._key_edit.text().strip() or None
        dev_id = self._generate_device_id(host)

        self._save_btn.setEnabled(False)
        self._show_banner("Registering device...", is_error=False)

        def task() -> RemoteDevice:
            dev = self._client.add_device(
                id=dev_id,
                hostname=host,
                port=port,
                username=user,
                display_name=name,
                ssh_key_path=key,
            )
            # Attempt initial connection
            try:
                self._client.connect_device(dev_id)
            except Exception:
                pass
            return dev

        def on_success(dev: RemoteDevice) -> None:
            self.created_device = dev
            self.accept()

        def on_error(msg: str, exc: Any) -> None:
            self._save_btn.setEnabled(True)
            self._show_banner(f"Failed to add device: {msg}", is_error=True)

        run_async_task(task, on_success=on_success, on_error=on_error)
