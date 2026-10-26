"""Dock widget presenting detailed properties, unit file, logs, and live resource usage."""

import os
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QDockWidget,
    QFormLayout,
    QLabel,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import (
    Service,
    ServiceLogs,
    ServiceResources,
    ServiceUnitFile,
)
from servicedeck.gui.workers.service_worker import run_async_task


def format_bytes(bytes_val: int | float | None) -> str:
    """Format byte counts into human-readable data size string."""
    if bytes_val is None or bytes_val < 0:
        return "N/A"
    units = ["B", "KB", "MB", "GB", "TB"]
    val = float(bytes_val)
    for unit in units:
        if val < 1024 or unit == "TB":
            return f"{val:.1f} {unit}" if unit != "B" else f"{int(val)} B"
        val /= 1024.0
    return f"{bytes_val} B"


def format_running_since(timestamp_usec: int | None) -> str:
    """Format microsecond timestamp into local date-time string."""
    if timestamp_usec is None or timestamp_usec <= 0:
        return "N/A"
    try:
        dt = datetime.fromtimestamp(timestamp_usec / 1_000_000).astimezone()
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return "N/A"


def format_duration(total_seconds: int | float) -> str:
    """Format total seconds into human-readable duration."""
    safe_seconds = max(0, int(total_seconds))
    days = safe_seconds // 86400
    hours = (safe_seconds % 86400) // 3600
    minutes = (safe_seconds % 3600) // 60
    seconds = safe_seconds % 60
    if days > 0:
        return f"{days}d {hours}h {minutes}m {seconds}s"
    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes > 0:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


class ServiceDetailPanel(QDockWidget):
    """Bottom dock widget showing tabbed details for the selected service."""

    def __init__(self, parent: Any = None, client: ServiceDeckClient | None = None) -> None:
        super().__init__("Service Details", parent)
        self.setObjectName("detailPanel")
        self.setMinimumHeight(200)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetVerticalTitleBar
        )
        self._client: ServiceDeckClient | None = client
        self._current_service: Service | None = None
        self._current_scope: str = "user"
        self._current_device_id: str | None = None

        # Previous samples for rate/CPU calculations
        self._previous_cpu_ns: int | None = None
        self._previous_read_bytes: int | None = None
        self._previous_write_bytes: int | None = None
        self._previous_sample_time: float | None = None

        self._setup_ui()
        self._setup_timers()

    def set_client(self, client: ServiceDeckClient) -> None:
        """Assign or update the API client instance."""
        self._client = client

    def _setup_timers(self) -> None:
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(5000)  # 5 seconds default
        self._log_timer.timeout.connect(self.refresh_service_logs)

        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(2000)  # 2 seconds default
        self._resource_timer.timeout.connect(self.refresh_resource_usage)

    def set_refresh_intervals(self, log_interval_sec: int, res_interval_sec: int) -> None:
        """Update polling timer intervals in seconds."""
        self._log_timer.setInterval(max(1000, log_interval_sec * 1000))
        self._resource_timer.setInterval(max(500, res_interval_sec * 1000))

    def _setup_ui(self) -> None:
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setObjectName("detailTabs")
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # ─── Tab 1: Properties ───
        props_widget = QWidget()
        props_layout = QFormLayout(props_widget)
        props_layout.setContentsMargins(16, 16, 16, 16)
        props_layout.setSpacing(8)

        def make_label(text: str = "-") -> QLabel:
            lbl = QLabel(text)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lbl

        self._name_val = make_label()
        self._desc_val = make_label()
        self._active_val = make_label()
        self._sub_state_val = make_label()
        self._load_val = make_label()
        self._enabled_val = make_label()
        self._path_val = make_label()
        self._scope_val = make_label()

        bold_font = QFont()
        bold_font.setBold(True)

        def add_row(label_text: str, val_widget: QLabel) -> None:
            lbl = QLabel(label_text)
            lbl.setFont(bold_font)
            props_layout.addRow(lbl, val_widget)

        add_row("Service Name:", self._name_val)
        add_row("Description:", self._desc_val)
        add_row("Active State:", self._active_val)
        add_row("Sub State:", self._sub_state_val)
        add_row("Load State:", self._load_val)
        add_row("Enabled:", self._enabled_val)
        add_row("Unit Path:", self._path_val)
        add_row("Scope:", self._scope_val)

        self._tab_widget.addTab(props_widget, "Properties")

        # ─── Tab 2: Unit File ───
        mono_font = QFont("Monospace", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)

        self._unit_file_edit = QTextEdit()
        self._unit_file_edit.setReadOnly(True)
        self._unit_file_edit.setObjectName("unitFileViewer")
        self._unit_file_edit.setFont(mono_font)
        self._tab_widget.addTab(self._unit_file_edit, "Unit File")

        # ─── Tab 3: Service Logs ───
        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setObjectName("serviceLogViewer")
        self._log_edit.setFont(mono_font)
        self._tab_widget.addTab(self._log_edit, "Service Logs")

        # ─── Tab 4: Resource Usage ───
        res_widget = QWidget()
        res_layout = QFormLayout(res_widget)
        res_layout.setContentsMargins(16, 16, 16, 16)
        res_layout.setSpacing(8)

        def add_res_row(label_text: str) -> QLabel:
            val_lbl = make_label("N/A")
            lbl = QLabel(label_text)
            lbl.setFont(bold_font)
            res_layout.addRow(lbl, val_lbl)
            return val_lbl

        self._running_since_val = add_res_row("Running Since:")
        self._uptime_val = add_res_row("Uptime:")
        self._cpu_val = add_res_row("CPU:")
        self._mem_val = add_res_row("Memory:")
        self._disk_read_val = add_res_row("Disk Read:")
        self._disk_write_val = add_res_row("Disk Write:")
        self._procs_val = add_res_row("Processes:")
        self._threads_val = add_res_row("Threads:")

        self._tab_widget.addTab(res_widget, "Resource Usage")

        self.setWidget(self._tab_widget)

    def _on_tab_changed(self, index: int) -> None:
        """Fetch fresh tab data immediately upon switching."""
        if not self._current_service:
            return
        if index == 1:  # Unit File
            self.refresh_unit_file()
        elif index == 2:  # Logs
            self.refresh_service_logs()
        elif index == 3:  # Resources
            self.refresh_resource_usage()

    def show_service_details(
        self,
        service: Service,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Populate the details panel with properties for the given service."""
        self._current_service = service
        self._current_scope = scope or service.scope
        self._current_device_id = device_id
        self.reset_resource_usage_state()

        self._name_val.setText(service.name)
        self._desc_val.setText(service.description or "(None)")
        self._active_val.setText(service.active_state.upper())
        self._sub_state_val.setText(service.sub_state)
        self._load_val.setText(service.load_state)
        self._enabled_val.setText(service.unit_file_state.upper())
        self._scope_val.setText(self._current_scope.upper())
        self._path_val.setText("-")

        # Active state coloring
        active = service.active_state.lower()
        if active == "active":
            self._active_val.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif active == "failed":
            self._active_val.setStyleSheet("color: #F44336; font-weight: bold;")
        elif active == "inactive":
            self._active_val.setStyleSheet("color: #9E9E9E; font-weight: bold;")
        else:
            self._active_val.setStyleSheet("color: #FFA726; font-weight: bold;")

        # Enabled state coloring
        enabled = service.unit_file_state.lower()
        if enabled == "enabled":
            self._enabled_val.setStyleSheet("color: #4CAF50; font-weight: bold;")
        elif enabled == "disabled":
            self._enabled_val.setStyleSheet("color: #F44336; font-weight: bold;")
        elif enabled == "masked":
            self._enabled_val.setStyleSheet("color: #795548; font-weight: bold;")
        else:
            self._enabled_val.setStyleSheet("color: #9E9E9E;")

        # Trigger data fetching
        self.refresh_unit_file()
        self.refresh_service_logs()
        self.refresh_resource_usage()

        self._log_timer.start()
        self._resource_timer.start()

        self.show()

    def refresh_unit_file(self) -> None:
        """Fetch on-disk unit file content asynchronously."""
        if not self._client or not self._current_service:
            return

        service_name = self._current_service.name
        scope = self._current_scope
        device_id = self._current_device_id

        def task() -> ServiceUnitFile:
            return self._client.get_unit_file(service_name, scope=scope, device_id=device_id)

        def on_success(res: ServiceUnitFile) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            self._path_val.setText(res.fragment_path or "(Generated/Transient)")
            self._unit_file_edit.setPlainText(res.content)

        def on_error(msg: str, exc: Any) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            self._unit_file_edit.setPlainText(f"# Failed to load unit file:\n# {msg}")

        run_async_task(task, on_success=on_success, on_error=on_error)

    def refresh_service_logs(self) -> None:
        """Fetch recent journal logs asynchronously."""
        if not self._client or not self._current_service:
            return

        service_name = self._current_service.name
        scope = self._current_scope
        device_id = self._current_device_id

        def task() -> ServiceLogs:
            return self._client.get_logs(service_name, lines=200, scope=scope, device_id=device_id)

        def on_success(res: ServiceLogs) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            scrollbar = self._log_edit.verticalScrollBar()
            was_at_bottom = scrollbar.value() >= (scrollbar.maximum() - 25)
            self._log_edit.setPlainText(res.logs)
            if was_at_bottom:
                cursor = self._log_edit.textCursor()
                cursor.movePosition(QTextCursor.MoveOperation.End)
                self._log_edit.setTextCursor(cursor)

        def on_error(msg: str, exc: Any) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            # Only update if empty to avoid clobbering existing logs on temporary poll glitch
            if not self._log_edit.toPlainText():
                self._log_edit.setPlainText(f"# Failed to load logs:\n# {msg}")

        run_async_task(task, on_success=on_success, on_error=on_error)

    def refresh_resource_usage(self) -> None:
        """Fetch runtime resource metrics and compute CPU / I/O rates."""
        if not self._client or not self._current_service:
            return

        service_name = self._current_service.name
        scope = self._current_scope
        device_id = self._current_device_id

        def task() -> ServiceResources:
            return self._client.get_resources(service_name, scope=scope, device_id=device_id)

        def on_success(res: ServiceResources) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return

            now = time.time()

            # Running since & uptime
            if res.active_enter_timestamp and res.active_state == "active":
                self._running_since_val.setText(format_running_since(res.active_enter_timestamp))
                uptime_sec = max(0.0, now - (res.active_enter_timestamp / 1_000_000))
                self._uptime_val.setText(format_duration(uptime_sec))
            else:
                self._running_since_val.setText("N/A")
                self._uptime_val.setText("N/A")

            # Memory
            if res.memory_current_bytes is not None:
                self._mem_val.setText(format_bytes(res.memory_current_bytes))
            else:
                self._mem_val.setText("N/A")

            # Processes & Threads
            if res.main_pid is not None and res.main_pid > 0:
                self._procs_val.setText(f"1 (PID: {res.main_pid})")
            else:
                self._procs_val.setText("N/A")

            if res.tasks_current is not None:
                self._threads_val.setText(str(res.tasks_current))
            else:
                self._threads_val.setText("N/A")

            # Rate calculations (CPU, Disk Read, Disk Write)
            elapsed_sec = (now - self._previous_sample_time) if self._previous_sample_time else 0.0

            if (
                res.cpu_usage_nsec is not None
                and self._previous_cpu_ns is not None
                and elapsed_sec > 0
            ):
                cpu_delta_ns = (
                    res.cpu_usage_nsec - self._previous_cpu_ns
                    if res.cpu_usage_nsec >= self._previous_cpu_ns
                    else 0
                )
                cpu_logical_cores = os.cpu_count() or 1
                aggregate_pct = (cpu_delta_ns / (elapsed_sec * 1e9)) * 100.0
                normalized_pct = max(0.0, min(100.0, aggregate_pct / cpu_logical_cores))
                self._cpu_val.setText(f"{normalized_pct:.1f}%")
            else:
                self._cpu_val.setText("N/A")

            if (
                res.disk_read_bytes is not None
                and self._previous_read_bytes is not None
                and elapsed_sec > 0
            ):
                read_delta = (
                    res.disk_read_bytes - self._previous_read_bytes
                    if res.disk_read_bytes >= self._previous_read_bytes
                    else 0
                )
                rate = read_delta / elapsed_sec
                self._disk_read_val.setText(f"{format_bytes(rate)}/s")
            elif res.disk_read_bytes is not None:
                self._disk_read_val.setText(format_bytes(res.disk_read_bytes))
            else:
                self._disk_read_val.setText("N/A")

            if (
                res.disk_write_bytes is not None
                and self._previous_write_bytes is not None
                and elapsed_sec > 0
            ):
                write_delta = (
                    res.disk_write_bytes - self._previous_write_bytes
                    if res.disk_write_bytes >= self._previous_write_bytes
                    else 0
                )
                rate = write_delta / elapsed_sec
                self._disk_write_val.setText(f"{format_bytes(rate)}/s")
            elif res.disk_write_bytes is not None:
                self._disk_write_val.setText(format_bytes(res.disk_write_bytes))
            else:
                self._disk_write_val.setText("N/A")

            # Store previous values for next interval
            self._previous_cpu_ns = res.cpu_usage_nsec
            self._previous_read_bytes = res.disk_read_bytes
            self._previous_write_bytes = res.disk_write_bytes
            self._previous_sample_time = now

        def on_error(msg: str, exc: Any) -> None:
            pass

        run_async_task(task, on_success=on_success, on_error=on_error)

    def reset_resource_usage_state(self) -> None:
        """Reset metric state and previous samples."""
        self._running_since_val.setText("-")
        self._uptime_val.setText("-")
        self._cpu_val.setText("-")
        self._mem_val.setText("-")
        self._disk_read_val.setText("-")
        self._disk_write_val.setText("-")
        self._procs_val.setText("-")
        self._threads_val.setText("-")
        self._previous_cpu_ns = None
        self._previous_read_bytes = None
        self._previous_write_bytes = None
        self._previous_sample_time = None

    def stop_timers(self) -> None:
        """Stop periodic polling timers."""
        self._log_timer.stop()
        self._resource_timer.stop()

    def clear(self) -> None:
        """Reset panel to empty state and stop polling."""
        self.stop_timers()
        self._current_service = None
        self._name_val.setText("-")
        self._desc_val.setText("-")
        self._active_val.setText("-")
        self._active_val.setStyleSheet("")
        self._sub_state_val.setText("-")
        self._load_val.setText("-")
        self._enabled_val.setText("-")
        self._enabled_val.setStyleSheet("")
        self._path_val.setText("-")
        self._scope_val.setText("-")
        self._unit_file_edit.clear()
        self._log_edit.clear()
        self.reset_resource_usage_state()

    def hideEvent(self, event: Any) -> None:
        """Stop background timers when panel is hidden."""
        self.stop_timers()
        super().hideEvent(event)

    def closeEvent(self, event: Any) -> None:
        """Stop background timers when panel is closed."""
        self.stop_timers()
        super().closeEvent(event)
