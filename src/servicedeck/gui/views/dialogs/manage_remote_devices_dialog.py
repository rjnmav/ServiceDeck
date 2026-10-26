"""Dialog for reviewing, connecting, and managing configured remote Linux hosts."""

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.remote import RemoteDevice
from servicedeck.gui.views.dialogs.add_remote_device_dialog import AddRemoteDeviceDialog
from servicedeck.gui.workers.service_worker import run_async_task


class ManageRemoteDevicesDialog(QDialog):
    """Dialog displaying configured remote devices with connect, disconnect, and remove options."""

    def __init__(self, parent: Any = None, client: ServiceDeckClient | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manage Remote Hosts")
        self.setMinimumSize(680, 380)
        self.setObjectName("manageRemoteDevicesDialog")
        self._client = client
        self.selected_device_id: str | None = None

        self._setup_ui()
        self.refresh_devices()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        # Header
        title_label = QLabel("Configured Remote Hosts", self)
        title_font = QFont()
        title_font.setPointSize(13)
        title_font.setBold(True)
        title_label.setFont(title_font)
        layout.addWidget(title_label)

        # Table
        self._table = QTableWidget(self)
        self._table.setColumnCount(5)
        self._table.setHorizontalHeaderLabels(["Name", "Host / IP", "Port", "User", "Status"])
        self._table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setAlternatingRowColors(True)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self._table)

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self._add_btn = QPushButton("+ Add Host...", self)
        self._add_btn.clicked.connect(self._on_add_clicked)
        btn_layout.addWidget(self._add_btn)

        self._connect_btn = QPushButton("Connect", self)
        self._connect_btn.setEnabled(False)
        self._connect_btn.clicked.connect(self._on_connect_clicked)
        btn_layout.addWidget(self._connect_btn)

        self._disconnect_btn = QPushButton("Disconnect", self)
        self._disconnect_btn.setEnabled(False)
        self._disconnect_btn.clicked.connect(self._on_disconnect_clicked)
        btn_layout.addWidget(self._disconnect_btn)

        self._remove_btn = QPushButton("Remove", self)
        self._remove_btn.setEnabled(False)
        self._remove_btn.clicked.connect(self._on_remove_clicked)
        btn_layout.addWidget(self._remove_btn)

        btn_layout.addStretch()

        self._switch_btn = QPushButton("Switch To Host", self)
        self._switch_btn.setEnabled(False)
        self._switch_btn.setStyleSheet(
            "background-color: #1971c2; color: #ffffff; font-weight: bold; padding: 6px 14px; border-radius: 6px;"
        )
        self._switch_btn.clicked.connect(self._on_switch_clicked)
        btn_layout.addWidget(self._switch_btn)

        self._close_btn = QPushButton("Close", self)
        self._close_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self._close_btn)

        layout.addLayout(btn_layout)

    def refresh_devices(self) -> None:
        """Fetch remote device list from backend."""
        if not self._client:
            return

        def task() -> list[RemoteDevice]:
            return self._client.list_devices()

        def on_success(devices: list[RemoteDevice]) -> None:
            self._table.setRowCount(len(devices))
            for row, dev in enumerate(devices):
                name_item = QTableWidgetItem(dev.display_name)
                name_item.setData(Qt.ItemDataRole.UserRole, dev.id)

                host_item = QTableWidgetItem(dev.hostname)
                port_item = QTableWidgetItem(str(dev.port))
                user_item = QTableWidgetItem(dev.username or "(default)")

                status_str = "🟢 Connected" if dev.connected else "⚪ Offline"
                status_item = QTableWidgetItem(status_str)

                self._table.setItem(row, 0, name_item)
                self._table.setItem(row, 1, host_item)
                self._table.setItem(row, 2, port_item)
                self._table.setItem(row, 3, user_item)
                self._table.setItem(row, 4, status_item)

            self._on_selection_changed()

        run_async_task(task, on_success=on_success)

    def _selected_device_id(self) -> str | None:
        rows = self._table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self._table.item(rows[0].row(), 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_selection_changed(self) -> None:
        has_sel = self._selected_device_id() is not None
        self._connect_btn.setEnabled(has_sel)
        self._disconnect_btn.setEnabled(has_sel)
        self._remove_btn.setEnabled(has_sel)
        self._switch_btn.setEnabled(has_sel)

    def _on_add_clicked(self) -> None:
        dlg = AddRemoteDeviceDialog(self, client=self._client)
        if dlg.exec() and dlg.created_device:
            self.refresh_devices()

    def _on_connect_clicked(self) -> None:
        dev_id = self._selected_device_id()
        if not dev_id or not self._client:
            return

        def task() -> None:
            self._client.connect_device(dev_id)

        def on_success(res: Any) -> None:
            self.refresh_devices()

        def on_error(msg: str, exc: Any) -> None:
            QMessageBox.critical(self, "Connection Error", f"Failed to connect: {msg}")

        run_async_task(task, on_success=on_success, on_error=on_error)

    def _on_disconnect_clicked(self) -> None:
        dev_id = self._selected_device_id()
        if not dev_id or not self._client:
            return

        def task() -> None:
            self._client.disconnect_device(dev_id)

        def on_success(res: Any) -> None:
            self.refresh_devices()

        run_async_task(task, on_success=on_success)

    def _on_remove_clicked(self) -> None:
        dev_id = self._selected_device_id()
        if not dev_id or not self._client:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Remove",
            f"Are you sure you want to remove remote device '{dev_id}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def task() -> None:
            self._client.remove_device(dev_id)

        def on_success(res: Any) -> None:
            self.refresh_devices()

        run_async_task(task, on_success=on_success)

    def _on_switch_clicked(self) -> None:
        dev_id = self._selected_device_id()
        if dev_id:
            self.selected_device_id = dev_id
            self.accept()
