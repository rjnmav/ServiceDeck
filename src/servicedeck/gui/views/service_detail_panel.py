"""Dock widget presenting detailed properties, unit file, logs, and live resource usage."""

import collections
import os
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QCheckBox,
    QDockWidget,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
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
from servicedeck.gui.workers.stream_worker import StreamWorker

#: Journal lines kept in memory for the log view (and its filter).
LOG_BUFFER_LINES = 5000
#: Recent lines fetched when following starts.
LOG_INITIAL_LINES = 200


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

        # Followed logs (journalctl -f style)
        self._log_lines: collections.deque[str] = collections.deque(maxlen=LOG_BUFFER_LINES)
        self._pending_log_lines: list[str] = []
        self._log_worker: StreamWorker | None = None
        self._retired_workers: dict[int, StreamWorker] = {}
        self._log_filter = ""

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

        # Coalesces bursts of followed lines into one view update.
        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(50)
        self._log_flush_timer.timeout.connect(self._flush_log_lines)

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
        logs_widget = QWidget()
        logs_layout = QVBoxLayout(logs_widget)
        logs_layout.setContentsMargins(0, 4, 0, 0)
        logs_layout.setSpacing(4)

        controls = QHBoxLayout()
        controls.setContentsMargins(8, 0, 8, 0)
        self._follow_check = QCheckBox("Follow")
        self._follow_check.setObjectName("logFollowToggle")
        self._follow_check.setChecked(True)
        self._follow_check.setToolTip(
            "Stream new journal lines as they are written (pause to stop)"
        )
        self._follow_check.toggled.connect(self._on_follow_toggled)
        self._autoscroll_check = QCheckBox("Auto-scroll")
        self._autoscroll_check.setObjectName("logAutoScrollToggle")
        self._autoscroll_check.setChecked(True)
        self._autoscroll_check.toggled.connect(self._on_autoscroll_toggled)
        self._log_filter_edit = QLineEdit()
        self._log_filter_edit.setObjectName("logFilter")
        self._log_filter_edit.setPlaceholderText("Filter log lines…")
        self._log_filter_edit.setClearButtonEnabled(True)
        self._log_filter_edit.textChanged.connect(self._on_log_filter_changed)
        self._log_clear_button = QPushButton("Clear")
        self._log_clear_button.setObjectName("logClearButton")
        self._log_clear_button.clicked.connect(self.clear_log_view)
        self._log_status = QLabel("")
        self._log_status.setObjectName("logStatus")
        controls.addWidget(self._follow_check)
        controls.addWidget(self._autoscroll_check)
        controls.addWidget(self._log_filter_edit, 1)
        controls.addWidget(self._log_clear_button)
        controls.addWidget(self._log_status)
        logs_layout.addLayout(controls)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setObjectName("serviceLogViewer")
        self._log_edit.setFont(mono_font)
        self._log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        logs_layout.addWidget(self._log_edit, 1)
        self._tab_widget.addTab(logs_widget, "Service Logs")

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
            if not self.is_following_logs:
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
        self._apply_service_properties(service)
        self._path_val.setText("-")

        # Trigger data fetching
        self.refresh_unit_file()
        self.refresh_resource_usage()
        self._resource_timer.start()
        self._restart_log_view()

        self.show()

    def update_service_state(self, service: Service) -> None:
        """Refresh the shown properties after a live change, without reloading the tabs."""
        if self._current_service is None or self._current_service.name != service.name:
            return
        self._current_service = service
        self._apply_service_properties(service)

    def _apply_service_properties(self, service: Service) -> None:
        self._name_val.setText(service.name)
        self._desc_val.setText(service.description or "(None)")
        self._active_val.setText(service.active_state.upper())
        self._sub_state_val.setText(service.sub_state)
        self._load_val.setText(service.load_state)
        self._enabled_val.setText(service.unit_file_state.upper())
        self._scope_val.setText(self._current_scope.upper())

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
            if self.is_following_logs:
                return
            scrollbar = self._log_edit.verticalScrollBar()
            position = scrollbar.value()
            self._log_lines.clear()
            self._log_lines.extend(res.logs.splitlines())
            self._render_log_lines()
            if not self._autoscroll_check.isChecked():
                scrollbar.setValue(position)

        def on_error(msg: str, exc: Any) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            # Only update if empty to avoid clobbering existing logs on temporary poll glitch
            if not self._log_edit.toPlainText():
                self._log_edit.setPlainText(f"# Failed to load logs:\n# {msg}")

        run_async_task(task, on_success=on_success, on_error=on_error)

    # --- Followed logs ---

    @property
    def is_following_logs(self) -> bool:
        """True while a live log stream is open for the shown service."""
        return self._log_worker is not None

    def _restart_log_view(self) -> None:
        """Start over for the current service: follow its journal, or poll when paused."""
        self._stop_log_follow()
        self._log_timer.stop()
        self.clear_log_view()
        if self._follow_check.isChecked():
            self._start_log_follow()
        else:
            self._log_status.setText("Paused")
            self.refresh_service_logs()

    def _start_log_follow(self) -> None:
        if not self._client or not self._current_service:
            return
        client = self._client
        name = self._current_service.name
        scope = self._current_scope
        device_id = self._current_device_id

        worker = StreamWorker(
            lambda: client.follow_logs(
                name, lines=LOG_INITIAL_LINES, scope=scope, device_id=device_id
            ),
            name="logs",
        )
        worker.signals.item.connect(self._on_log_line)
        worker.signals.failed.connect(self._on_log_follow_failed)
        worker.signals.finished.connect(self._on_log_worker_finished)
        self._log_worker = worker
        self._log_status.setText("Following")
        self._log_status.setToolTip("")
        worker.start()

    def _stop_log_follow(self) -> None:
        worker, self._log_worker = self._log_worker, None
        if worker is not None:
            worker.stop()
            self._retired_workers[worker.token] = worker
        self._pending_log_lines.clear()

    def _is_current_log_worker(self, token: int) -> bool:
        return self._log_worker is not None and self._log_worker.token == token

    def _on_log_line(self, token: int, line: str) -> None:
        if not self._is_current_log_worker(token):
            return
        self._pending_log_lines.append(line)
        if not self._log_flush_timer.isActive():
            self._log_flush_timer.start()

    def _flush_log_lines(self) -> None:
        lines, self._pending_log_lines = self._pending_log_lines, []
        if not lines:
            return
        self._log_lines.extend(lines)
        shown = [line for line in lines if self._matches_log_filter(line)]
        if not shown:
            return
        scrollbar = self._log_edit.verticalScrollBar()
        position = scrollbar.value()
        cursor = QTextCursor(self._log_edit.document())
        cursor.movePosition(QTextCursor.MoveOperation.End)
        prefix = "\n" if not self._log_edit.document().isEmpty() else ""
        cursor.insertText(prefix + "\n".join(shown))
        self._trim_log_view()
        if self._autoscroll_check.isChecked():
            self._scroll_logs_to_end()
        else:
            scrollbar.setValue(position)

    def _trim_log_view(self) -> None:
        document = self._log_edit.document()
        excess = document.blockCount() - LOG_BUFFER_LINES
        if excess <= 0:
            return
        cursor = QTextCursor(document)
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(
            QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor, excess
        )
        cursor.removeSelectedText()

    def _scroll_logs_to_end(self) -> None:
        scrollbar = self._log_edit.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _on_log_follow_failed(self, token: int, message: str, exc: Any) -> None:
        if not self._is_current_log_worker(token):
            return
        self._log_worker = None
        # Fall back to periodic polling (e.g. an older backend without streaming).
        self._log_status.setText(f"Polling every {self._log_timer.interval() // 1000}s")
        self._log_status.setToolTip(f"Live log follow unavailable: {message}")
        self.refresh_service_logs()
        self._log_timer.start()

    def _on_log_worker_finished(self, token: int) -> None:
        self._retired_workers.pop(token, None)
        if self._is_current_log_worker(token):
            # The stream ended on its own (journalctl exited); show what we have.
            self._log_worker = None
            self._log_status.setText("Stopped")

    def _on_follow_toggled(self, checked: bool) -> None:
        if not self._current_service:
            return
        if checked:
            self._restart_log_view()
        else:
            self._stop_log_follow()
            self._log_status.setText("Paused")

    def _on_autoscroll_toggled(self, checked: bool) -> None:
        if checked:
            self._scroll_logs_to_end()

    def _matches_log_filter(self, line: str) -> bool:
        return not self._log_filter or self._log_filter in line.lower()

    def _on_log_filter_changed(self, text: str) -> None:
        self._log_filter = text.strip().lower()
        self._render_log_lines()

    def _render_log_lines(self) -> None:
        self._log_edit.setPlainText(
            "\n".join(line for line in self._log_lines if self._matches_log_filter(line))
        )
        if self._autoscroll_check.isChecked():
            self._scroll_logs_to_end()

    def clear_log_view(self) -> None:
        """Empty the log view and its buffer (following continues)."""
        self._log_lines.clear()
        self._pending_log_lines.clear()
        self._log_edit.clear()

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
        """Stop periodic polling timers and the live log stream."""
        self._log_timer.stop()
        self._resource_timer.stop()
        self._stop_log_follow()

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
        self.clear_log_view()
        self._log_status.setText("")
        self._log_status.setToolTip("")
        self.reset_resource_usage_state()

    def showEvent(self, event: Any) -> None:
        """Resume live data when the panel comes back (e.g. after being hidden)."""
        super().showEvent(event)
        if self._current_service is None:
            return
        if not self._resource_timer.isActive():
            self._resource_timer.start()
        if (
            self._follow_check.isChecked()
            and not self.is_following_logs
            and not self._log_timer.isActive()
        ):
            self._restart_log_view()

    def hideEvent(self, event: Any) -> None:
        """Stop background timers when panel is hidden."""
        self.stop_timers()
        super().hideEvent(event)

    def closeEvent(self, event: Any) -> None:
        """Stop background timers when panel is closed."""
        self.stop_timers()
        super().closeEvent(event)
