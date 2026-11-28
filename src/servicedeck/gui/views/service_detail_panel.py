"""Right-side inspector drawer presenting contextual actions, overview, logs, and unit file."""

import collections
import os
import time
from datetime import datetime
from typing import Any

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
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
    format_ago,
)
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette
from servicedeck.gui.views.unit_highlighter import UnitFileHighlighter
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


class ServiceDetailPanel(QWidget):
    """Right-side inspector drawer showing contextual actions, overview, logs, and unit file."""

    action_requested = Signal(str)  # start, stop, restart, enable, disable, mask, unmask, reload
    close_requested = Signal()
    #: The user wants to edit the selected service's drop-in override.
    edit_override_requested = Signal()
    #: The user wants to remove the selected service's drop-ins (back to the vendor unit).
    revert_requested = Signal()
    #: The "notify me if this service fails" box was toggled by the user.
    watch_toggled = Signal(bool)

    def __init__(
        self,
        parent: Any = None,
        client: ServiceDeckClient | None = None,
        theme: str = "dark",
    ) -> None:
        super().__init__(parent)
        self.setObjectName("detailPanel")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setWindowTitle("Service Details")
        self.setMinimumWidth(380)

        self._client: ServiceDeckClient | None = client
        self._theme = theme
        self._current_service: Service | None = None
        self._current_scope: str = "user"
        self._current_device_id: str | None = None
        self._actions_enabled = True
        self._unit_file: ServiceUnitFile | None = None
        self._setting_watch = False

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
        self.refresh_theme(theme)

    def set_client(self, client: ServiceDeckClient) -> None:
        """Assign or update the API client instance."""
        self._client = client

    def _setup_timers(self) -> None:
        self._log_timer = QTimer(self)
        self._log_timer.setInterval(5000)
        self._log_timer.timeout.connect(self.refresh_service_logs)

        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(2000)
        self._resource_timer.timeout.connect(self.refresh_resource_usage)

        self._log_flush_timer = QTimer(self)
        self._log_flush_timer.setSingleShot(True)
        self._log_flush_timer.setInterval(50)
        self._log_flush_timer.timeout.connect(self._flush_log_lines)

    def set_refresh_intervals(self, log_interval_sec: int, res_interval_sec: int) -> None:
        """Update polling timer intervals in seconds."""
        self._log_timer.setInterval(max(1000, log_interval_sec * 1000))
        self._resource_timer.setInterval(max(500, res_interval_sec * 1000))

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─── Pinned Inspector Header ───
        header = QWidget(self)
        header.setObjectName("inspectorHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QVBoxLayout(header)
        header_layout.setContentsMargins(18, 14, 14, 14)
        header_layout.setSpacing(8)

        title_row = QHBoxLayout()
        title_row.setSpacing(8)

        self._name_val = QLabel("-")
        self._name_val.setObjectName("inspectorTitle")
        self._name_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self._name_val.setWordWrap(True)
        title_row.addWidget(self._name_val, 1)

        self._close_btn = QPushButton(header)
        self._close_btn.setObjectName("iconBtn")
        self._close_btn.setFixedSize(28, 28)
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.setToolTip("Close inspector (Esc)")
        self._close_btn.clicked.connect(self._on_close_clicked)
        title_row.addWidget(self._close_btn, 0, Qt.AlignmentFlag.AlignTop)
        header_layout.addLayout(title_row)

        self._desc_val = QLabel("-")
        self._desc_val.setObjectName("inspectorDesc")
        self._desc_val.setWordWrap(True)
        self._desc_val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        header_layout.addWidget(self._desc_val)

        # Pills Row + Dedicated Contextual Actions Row
        pills_row = QHBoxLayout()
        pills_row.setSpacing(6)

        self._active_val = QLabel("-")
        self._active_val.setObjectName("statusPill")
        pills_row.addWidget(self._active_val)

        self._enabled_val = QLabel("-")
        self._enabled_val.setObjectName("statusPill")
        pills_row.addWidget(self._enabled_val)
        pills_row.addStretch()
        header_layout.addLayout(pills_row)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)

        self._start_btn = QPushButton("Start", header)
        self._start_btn.setObjectName("successBtn")
        self._start_btn.setIconSize(QSize(13, 13))
        self._start_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._start_btn.clicked.connect(lambda: self.action_requested.emit("start"))
        action_row.addWidget(self._start_btn)

        self._restart_btn = QPushButton("Restart", header)
        self._restart_btn.setIconSize(QSize(13, 13))
        self._restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restart_btn.clicked.connect(lambda: self.action_requested.emit("restart"))
        action_row.addWidget(self._restart_btn)

        self._stop_btn = QPushButton("Stop", header)
        self._stop_btn.setObjectName("dangerBtn")
        self._stop_btn.setIconSize(QSize(13, 13))
        self._stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._stop_btn.clicked.connect(lambda: self.action_requested.emit("stop"))
        action_row.addWidget(self._stop_btn)

        action_row.addStretch()

        self._more_btn = QPushButton(header)
        self._more_btn.setObjectName("iconBtn")
        self._more_btn.setFixedSize(30, 30)
        self._more_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._more_btn.setToolTip("More service actions (Enable, Disable, Mask, Unmask)")
        self._more_btn.clicked.connect(self._show_more_actions)
        action_row.addWidget(self._more_btn)

        header_layout.addLayout(action_row)
        root.addWidget(header)

        # ─── Tabs: Overview | Logs | Unit File ───
        self._tab_widget = QTabWidget(self)
        self._tab_widget.setObjectName("detailTabs")
        self._tab_widget.currentChanged.connect(self._on_tab_changed)

        # Tab 1: Overview (Resources + Properties)
        overview_scroll = QScrollArea()
        overview_scroll.setObjectName("inspectorScroll")
        overview_scroll.setWidgetResizable(True)
        overview_scroll.setFrameShape(QFrame.Shape.NoFrame)
        overview_scroll.viewport().setObjectName("inspectorViewport")
        overview_scroll.viewport().setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

        overview_widget = QWidget()
        overview_widget.setObjectName("overviewPage")
        overview_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        overview_layout = QVBoxLayout(overview_widget)
        overview_layout.setContentsMargins(16, 14, 16, 16)
        overview_layout.setSpacing(14)

        res_heading = QLabel("Live Resources", overview_widget)
        res_heading.setObjectName("sidebarSectionLabel")
        overview_layout.addWidget(res_heading)

        res_grid = QGridLayout()
        res_grid.setSpacing(10)

        def make_metric_card(title: str) -> tuple[QFrame, QLabel]:
            card = QFrame(overview_widget)
            card.setObjectName("metricCard")
            card_layout = QVBoxLayout(card)
            card_layout.setContentsMargins(12, 10, 12, 10)
            card_layout.setSpacing(4)
            lbl = QLabel(title, card)
            lbl.setObjectName("metricLabel")
            val = QLabel("-", card)
            val.setObjectName("metricValue")
            val.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            card_layout.addWidget(lbl)
            card_layout.addWidget(val)
            return card, val

        cpu_card, self._cpu_val = make_metric_card("CPU")
        mem_card, self._mem_val = make_metric_card("Memory")
        procs_card, self._procs_val = make_metric_card("Main Process")
        threads_card, self._threads_val = make_metric_card("Tasks / Threads")
        uptime_card, self._uptime_val = make_metric_card("Uptime")
        since_card, self._running_since_val = make_metric_card("Running Since")
        disk_r_card, self._disk_read_val = make_metric_card("Disk Read")
        disk_w_card, self._disk_write_val = make_metric_card("Disk Write")

        res_grid.addWidget(cpu_card, 0, 0)
        res_grid.addWidget(mem_card, 0, 1)
        res_grid.addWidget(procs_card, 1, 0)
        res_grid.addWidget(threads_card, 1, 1)
        res_grid.addWidget(uptime_card, 2, 0)
        res_grid.addWidget(since_card, 2, 1)
        res_grid.addWidget(disk_r_card, 3, 0)
        res_grid.addWidget(disk_w_card, 3, 1)
        overview_layout.addLayout(res_grid)

        health_heading = QLabel("Health", overview_widget)
        health_heading.setObjectName("sidebarSectionLabel")
        overview_layout.addWidget(health_heading)

        health_card = QFrame(overview_widget)
        health_card.setObjectName("propGroup")
        health_grid = QGridLayout(health_card)
        health_grid.setContentsMargins(14, 12, 14, 12)
        health_grid.setHorizontalSpacing(14)
        health_grid.setVerticalSpacing(8)
        health_grid.setColumnStretch(1, 1)

        def make_health_val() -> QLabel:
            lbl = QLabel("-", health_card)
            lbl.setObjectName("propVal")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lbl

        self._restarts_val = make_health_val()
        self._restarts_val.setToolTip("Automatic restarts by systemd (NRestarts)")
        self._last_exit_val = make_health_val()
        self._last_exit_val.setToolTip("How the main process last ended")
        self._result_val = make_health_val()
        self._result_val.setToolTip("Outcome of the last run")
        self._failed_since_val = make_health_val()
        health_rows: list[tuple[str, QWidget]] = [
            ("Restarts", self._restarts_val),
            ("Last Exit", self._last_exit_val),
            ("Result", self._result_val),
            ("Failed", self._failed_since_val),
        ]
        self._failed_since_key = QLabel("Failed", health_card)
        for row_idx, (key_text, val_widget) in enumerate(health_rows):
            key_lbl = (
                self._failed_since_key if key_text == "Failed" else QLabel(key_text, health_card)
            )
            key_lbl.setObjectName("propKey")
            health_grid.addWidget(key_lbl, row_idx, 0, Qt.AlignmentFlag.AlignTop)
            health_grid.addWidget(val_widget, row_idx, 1)

        self._watch_check = QCheckBox("Notify me if this service fails", health_card)
        self._watch_check.setObjectName("watchToggle")
        self._watch_check.setToolTip(
            "Show a desktop notification when this service enters the failed state, "
            "even while another host or scope is shown."
        )
        self._watch_check.toggled.connect(self._on_watch_toggled)
        health_grid.addWidget(self._watch_check, len(health_rows), 0, 1, 2)
        self._set_failed_row_visible(False)
        overview_layout.addWidget(health_card)

        props_heading = QLabel("Unit Details", overview_widget)
        props_heading.setObjectName("sidebarSectionLabel")
        overview_layout.addWidget(props_heading)

        prop_card = QFrame(overview_widget)
        prop_card.setObjectName("propGroup")
        prop_grid = QGridLayout(prop_card)
        prop_grid.setContentsMargins(14, 12, 14, 12)
        prop_grid.setHorizontalSpacing(14)
        prop_grid.setVerticalSpacing(8)
        prop_grid.setColumnStretch(1, 1)

        def make_prop_val(text: str = "-") -> QLabel:
            lbl = QLabel(text, prop_card)
            lbl.setObjectName("propVal")
            lbl.setWordWrap(True)
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            return lbl

        self._sub_state_val = make_prop_val()
        self._load_val = make_prop_val()
        self._scope_val = make_prop_val()
        self._path_val = make_prop_val()

        prop_rows: list[tuple[str, QWidget]] = [
            ("Sub State", self._sub_state_val),
            ("Load State", self._load_val),
            ("Scope", self._scope_val),
            ("Unit Path", self._path_val),
        ]
        for row_idx, (key_text, val_widget) in enumerate(prop_rows):
            key_lbl = QLabel(key_text, prop_card)
            key_lbl.setObjectName("propKey")
            prop_grid.addWidget(key_lbl, row_idx, 0, Qt.AlignmentFlag.AlignTop)
            prop_grid.addWidget(val_widget, row_idx, 1)

        overview_layout.addWidget(prop_card)
        overview_layout.addStretch()
        overview_scroll.setWidget(overview_widget)
        self._tab_widget.addTab(overview_scroll, "Overview")

        # Tab 2: Service Logs
        mono_font = QFont("Monospace", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)

        logs_widget = QWidget()
        logs_widget.setObjectName("logsPage")
        logs_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        logs_layout = QVBoxLayout(logs_widget)
        logs_layout.setContentsMargins(12, 10, 12, 12)
        logs_layout.setSpacing(8)

        controls = QHBoxLayout()
        controls.setSpacing(8)
        self._follow_check = QCheckBox("Follow")
        self._follow_check.setObjectName("logFollowToggle")
        self._follow_check.setChecked(True)
        self._follow_check.setToolTip(
            "Stream new journal lines as they are written (uncheck to pause)"
        )
        self._follow_check.toggled.connect(self._on_follow_toggled)

        self._autoscroll_check = QCheckBox("Auto-scroll")
        self._autoscroll_check.setObjectName("logAutoScrollToggle")
        self._autoscroll_check.setChecked(True)
        self._autoscroll_check.toggled.connect(self._on_autoscroll_toggled)

        self._log_status = QLabel("")
        self._log_status.setObjectName("logStatus")

        self._log_clear_button = QPushButton("Clear")
        self._log_clear_button.setObjectName("logClearButton")
        self._log_clear_button.clicked.connect(self.clear_log_view)

        controls.addWidget(self._follow_check)
        controls.addWidget(self._autoscroll_check)
        controls.addStretch()
        controls.addWidget(self._log_status)
        controls.addWidget(self._log_clear_button)
        logs_layout.addLayout(controls)

        self._log_filter_edit = QLineEdit()
        self._log_filter_edit.setObjectName("logFilter")
        self._log_filter_edit.setPlaceholderText("Filter log lines...")
        self._log_filter_edit.setClearButtonEnabled(True)
        self._log_filter_edit.textChanged.connect(self._on_log_filter_changed)
        logs_layout.addWidget(self._log_filter_edit)

        self._log_edit = QTextEdit()
        self._log_edit.setReadOnly(True)
        self._log_edit.setObjectName("serviceLogViewer")
        self._log_edit.setFont(mono_font)
        self._log_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        logs_layout.addWidget(self._log_edit, 1)
        self._tab_widget.addTab(logs_widget, "Logs")

        # Tab 3: Unit File
        unit_widget = QWidget()
        unit_widget.setObjectName("unitFilePage")
        unit_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        unit_layout = QVBoxLayout(unit_widget)
        unit_layout.setContentsMargins(12, 10, 12, 12)
        unit_layout.setSpacing(8)

        unit_bar = QHBoxLayout()
        unit_bar.setSpacing(6)
        self._unit_path_hint = QLabel("Read-only systemd unit definition", unit_widget)
        self._unit_path_hint.setObjectName("contextSubtitle")
        self._unit_path_hint.setWordWrap(True)
        unit_bar.addWidget(self._unit_path_hint, 1)

        self._edit_override_btn = QPushButton("Edit", unit_widget)
        self._edit_override_btn.setObjectName("iconBtn")
        self._edit_override_btn.setIconSize(QSize(13, 13))
        self._edit_override_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_override_btn.setToolTip(
            "Edit a drop-in override (<unit>.d/override.conf), like 'systemctl edit'"
        )
        self._edit_override_btn.setEnabled(False)
        self._edit_override_btn.clicked.connect(self.edit_override_requested.emit)
        unit_bar.addWidget(self._edit_override_btn)

        self._revert_unit_btn = QPushButton("Revert", unit_widget)
        self._revert_unit_btn.setObjectName("iconBtn")
        self._revert_unit_btn.setIconSize(QSize(13, 13))
        self._revert_unit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._revert_unit_btn.setToolTip("Remove the overrides and use the vendor unit file again")
        self._revert_unit_btn.setEnabled(False)
        self._revert_unit_btn.clicked.connect(self.revert_requested.emit)
        unit_bar.addWidget(self._revert_unit_btn)

        self._copy_unit_btn = QPushButton("Copy", unit_widget)
        self._copy_unit_btn.setObjectName("iconBtn")
        self._copy_unit_btn.setIconSize(QSize(13, 13))
        self._copy_unit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._copy_unit_btn.clicked.connect(self._copy_unit_file)
        unit_bar.addWidget(self._copy_unit_btn)
        unit_layout.addLayout(unit_bar)

        self._unit_reload_warning = QLabel(
            "Unit files changed on disk since systemd last reloaded them.", unit_widget
        )
        self._unit_reload_warning.setObjectName("dialogBanner")
        self._unit_reload_warning.setProperty("state", "info")
        self._unit_reload_warning.setWordWrap(True)
        self._unit_reload_warning.hide()
        unit_layout.addWidget(self._unit_reload_warning)

        self._unit_file_edit = QTextEdit()
        self._unit_file_edit.setReadOnly(True)
        self._unit_file_edit.setObjectName("unitFileViewer")
        self._unit_file_edit.setFont(mono_font)
        self._unit_file_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._unit_highlighter = UnitFileHighlighter(self._unit_file_edit.document(), self._theme)
        unit_layout.addWidget(self._unit_file_edit, 1)
        self._tab_widget.addTab(unit_widget, "Unit File")

        root.addWidget(self._tab_widget, 1)

    def _on_close_clicked(self) -> None:
        self.hide()
        self.close_requested.emit()

    def _copy_unit_file(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._unit_file_edit.toPlainText())
            self._copy_unit_btn.setText("Copied")
            QTimer.singleShot(1500, lambda: self._copy_unit_btn.setText("Copy"))

    def set_actions_enabled(self, enabled: bool) -> None:
        """Enable or disable inspector action buttons while a service op is in flight."""
        self._actions_enabled = enabled
        self._start_btn.setEnabled(enabled)
        self._restart_btn.setEnabled(enabled)
        self._stop_btn.setEnabled(enabled)
        self._more_btn.setEnabled(enabled)
        self._update_unit_buttons()

    @property
    def current_unit_file(self) -> ServiceUnitFile | None:
        """The unit file (with drop-ins) last loaded for the selected service."""
        return self._unit_file

    @property
    def current_service(self) -> Service | None:
        return self._current_service

    @property
    def current_scope(self) -> str:
        return self._current_scope

    @property
    def current_device_id(self) -> str | None:
        return self._current_device_id

    def _update_unit_buttons(self) -> None:
        unit = self._unit_file
        loaded = unit is not None and self._current_service is not None
        self._edit_override_btn.setEnabled(
            self._actions_enabled and loaded and bool(unit and unit.override_path)
        )
        self._revert_unit_btn.setEnabled(
            self._actions_enabled and loaded and bool(unit and unit.editable_drop_ins)
        )

    def _show_more_actions(self) -> None:
        if not self._current_service:
            return
        menu = QMenu(self)
        palette = get_palette(self._theme)
        enabled_state = self._current_service.unit_file_state.lower()

        if enabled_state != "enabled":
            menu.addAction(
                IconHelper.svg_icon("check", palette.success_text),
                "Enable at Boot",
                lambda: self.action_requested.emit("enable"),
            )
        if enabled_state == "enabled":
            menu.addAction(
                IconHelper.svg_icon("ban", palette.danger_text),
                "Disable at Boot",
                lambda: self.action_requested.emit("disable"),
            )
        menu.addAction(
            IconHelper.svg_icon("refresh", palette.text_primary),
            "Reload Unit",
            lambda: self.action_requested.emit("reload"),
        )
        menu.addSeparator()
        if enabled_state == "masked":
            menu.addAction(
                IconHelper.svg_icon("unlock", palette.success_text),
                "Unmask",
                lambda: self.action_requested.emit("unmask"),
            )
        else:
            menu.addAction(
                IconHelper.svg_icon("lock", palette.masked_text),
                "Mask",
                lambda: self.action_requested.emit("mask"),
            )
        menu.exec(self._more_btn.mapToGlobal(self._more_btn.rect().bottomLeft()))

    def _on_tab_changed(self, index: int) -> None:
        """Fetch fresh tab data immediately upon switching."""
        if not self._current_service:
            return
        if index == 0:  # Overview
            self.refresh_resource_usage()
        elif index == 1:  # Logs
            if not self.is_following_logs:
                self.refresh_service_logs()
        elif index == 2:  # Unit File
            self.refresh_unit_file()

    def show_service_details(
        self,
        service: Service,
        scope: str | None = None,
        device_id: str | None = None,
    ) -> None:
        """Populate the inspector drawer with details for the given service."""
        self._current_service = service
        self._current_scope = scope or service.scope
        self._current_device_id = device_id
        self.reset_resource_usage_state()
        self._apply_service_properties(service)
        self._path_val.setText("-")
        self._unit_file = None
        self._update_unit_buttons()

        self.refresh_unit_file()
        self.refresh_resource_usage()
        self._resource_timer.start()
        self._restart_log_view()

        self.show()

    def update_service_state(self, service: Service) -> None:
        """Refresh the shown properties after a live change, without reloading tabs."""
        if self._current_service is None or self._current_service.name != service.name:
            return
        self._current_service = service
        self._apply_service_properties(service)

    def _apply_service_properties(self, service: Service) -> None:
        self._name_val.setText(service.name)
        self._desc_val.setText(service.description or "No description provided")
        self._active_val.setText(service.active_state.upper())
        self._sub_state_val.setText(service.sub_state)
        self._load_val.setText(service.load_state)
        self._enabled_val.setText(service.unit_file_state.upper())
        self._scope_val.setText(self._current_scope.upper())

        palette = get_palette(self._theme)
        active = service.active_state.lower()
        if active == "active":
            fg, bg, br = palette.success_text, palette.success_bg, palette.success_border
        elif active == "failed":
            fg, bg, br = palette.danger_text, palette.danger_bg, palette.danger_border
        elif active == "inactive":
            fg, bg, br = palette.muted_text, palette.muted_bg, palette.muted_border
        else:
            fg, bg, br = palette.warning_text, palette.warning_bg, palette.warning_border
        self._active_val.setStyleSheet(
            f"color: {fg}; background-color: {bg}; border: 1px solid {br}; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 700; font-size: 11px;"
        )

        enabled = service.unit_file_state.lower()
        if enabled == "enabled":
            efg, ebg, ebr = palette.success_text, palette.success_bg, palette.success_border
        elif enabled == "disabled":
            efg, ebg, ebr = palette.danger_text, palette.danger_bg, palette.danger_border
        elif enabled == "masked":
            efg, ebg, ebr = palette.masked_text, palette.masked_bg, palette.masked_border
        else:
            efg, ebg, ebr = palette.muted_text, palette.muted_bg, palette.muted_border
        self._enabled_val.setStyleSheet(
            f"color: {efg}; background-color: {ebg}; border: 1px solid {ebr}; "
            "border-radius: 10px; padding: 3px 10px; font-weight: 700; font-size: 11px;"
        )

        # Contextual primary actions: show Start when inactive/failed, Stop when active
        is_running = active in ("active", "activating", "reloading")
        self._start_btn.setVisible(not is_running)
        self._stop_btn.setVisible(is_running)
        self._restart_btn.setVisible(True)
        self.set_actions_enabled(self._actions_enabled)

    def refresh_theme(self, theme: str) -> None:
        """Update icons and status pill colors for the active theme."""
        self._theme = theme
        palette = get_palette(theme)
        self._close_btn.setIcon(IconHelper.svg_icon("close", palette.text_secondary))
        self._more_btn.setIcon(IconHelper.svg_icon("more", palette.text_primary))
        self._start_btn.setIcon(IconHelper.svg_icon("play", palette.success_text))
        self._stop_btn.setIcon(IconHelper.svg_icon("stop", palette.danger_text))
        self._restart_btn.setIcon(IconHelper.svg_icon("restart", palette.text_primary))
        self._copy_unit_btn.setIcon(IconHelper.svg_icon("copy", palette.text_primary))
        self._edit_override_btn.setIcon(IconHelper.svg_icon("edit", palette.text_primary))
        self._revert_unit_btn.setIcon(IconHelper.svg_icon("undo", palette.text_primary))
        if hasattr(self, "_unit_highlighter"):
            self._unit_highlighter.set_theme(theme)
        if self._current_service is not None:
            self._apply_service_properties(self._current_service)

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
            self.set_unit_file(res)

        def on_error(msg: str, exc: Any) -> None:
            if not self._current_service or self._current_service.name != service_name:
                return
            self._unit_file = None
            self._update_unit_buttons()
            self._unit_file_edit.setPlainText(f"# Failed to load unit file:\n# {msg}")

        run_async_task(task, on_success=on_success, on_error=on_error)

    def set_unit_file(self, unit: ServiceUnitFile) -> None:
        """Show a unit file with its drop-ins (``systemctl cat`` style)."""
        self._unit_file = unit
        path_text = unit.fragment_path or "(Generated/Transient)"
        self._path_val.setText(path_text)
        count = len(unit.drop_ins)
        if count:
            editable = len(unit.editable_drop_ins)
            noun = "drop-in" if count == 1 else "drop-ins"
            extra = f" ({editable} override{'s' if editable != 1 else ''})" if editable else ""
            self._unit_path_hint.setText(f"{path_text}  +  {count} {noun}{extra}")
        else:
            self._unit_path_hint.setText(path_text)
        self._unit_reload_warning.setVisible(unit.need_daemon_reload)
        self._unit_file_edit.setPlainText(unit.effective_text() if unit.drop_ins else unit.content)
        self._update_unit_buttons()

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
        self._log_status.setText(f"Polling every {self._log_timer.interval() // 1000}s")
        self._log_status.setToolTip(f"Live log follow unavailable: {message}")
        self.refresh_service_logs()
        self._log_timer.start()

    def _on_log_worker_finished(self, token: int) -> None:
        self._retired_workers.pop(token, None)
        if self._is_current_log_worker(token):
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
            self.apply_health(res, now)

            if res.active_enter_timestamp and res.active_state == "active":
                self._running_since_val.setText(format_running_since(res.active_enter_timestamp))
                uptime_sec = max(0.0, now - (res.active_enter_timestamp / 1_000_000))
                self._uptime_val.setText(format_duration(uptime_sec))
            else:
                self._running_since_val.setText("N/A")
                self._uptime_val.setText("N/A")

            if res.memory_current_bytes is not None:
                self._mem_val.setText(format_bytes(res.memory_current_bytes))
            else:
                self._mem_val.setText("N/A")

            if res.main_pid is not None and res.main_pid > 0:
                self._procs_val.setText(f"PID {res.main_pid}")
            else:
                self._procs_val.setText("N/A")

            if res.tasks_current is not None:
                self._threads_val.setText(str(res.tasks_current))
            else:
                self._threads_val.setText("N/A")

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
                self._disk_read_val.setText(f"{format_bytes(read_delta / elapsed_sec)}/s")
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
                self._disk_write_val.setText(f"{format_bytes(write_delta / elapsed_sec)}/s")
            elif res.disk_write_bytes is not None:
                self._disk_write_val.setText(format_bytes(res.disk_write_bytes))
            else:
                self._disk_write_val.setText("N/A")

            self._previous_cpu_ns = res.cpu_usage_nsec
            self._previous_read_bytes = res.disk_read_bytes
            self._previous_write_bytes = res.disk_write_bytes
            self._previous_sample_time = now

        def on_error(msg: str, exc: Any) -> None:
            pass

        run_async_task(task, on_success=on_success, on_error=on_error)

    def _set_failed_row_visible(self, visible: bool) -> None:
        self._failed_since_key.setVisible(visible)
        self._failed_since_val.setVisible(visible)

    def _on_watch_toggled(self, checked: bool) -> None:
        if not self._setting_watch:
            self.watch_toggled.emit(checked)

    def set_watched(self, watched: bool) -> None:
        """Reflect whether the shown service is watched, without emitting ``watch_toggled``."""
        self._setting_watch = True
        try:
            self._watch_check.setChecked(watched)
        finally:
            self._setting_watch = False

    @property
    def is_watched(self) -> bool:
        return self._watch_check.isChecked()

    def apply_health(self, res: ServiceResources, now: float | None = None) -> None:
        """Show restart count, last exit and failure time from a resources sample."""
        palette = get_palette(self._theme)
        if res.n_restarts is None:
            self._restarts_val.setText("N/A")
            self._restarts_val.setStyleSheet("")
        else:
            self._restarts_val.setText(str(res.n_restarts))
            self._restarts_val.setStyleSheet(
                f"color: {palette.warning_text}; font-weight: 700;" if res.n_restarts else ""
            )
        self._last_exit_val.setText(res.last_exit or "-")
        result = res.result or "-"
        self._result_val.setText(result)
        self._result_val.setStyleSheet(
            f"color: {palette.danger_text}; font-weight: 700;"
            if res.result and res.result != "success"
            else ""
        )
        failed_for = res.failed_for_seconds(now)
        if failed_for is None:
            self._set_failed_row_visible(False)
            self._failed_since_val.setText("-")
        else:
            since = format_running_since(res.state_change_timestamp)
            self._failed_since_val.setText(f"{format_ago(failed_for)} ago (since {since})")
            self._failed_since_val.setStyleSheet(f"color: {palette.danger_text};")
            self._set_failed_row_visible(True)

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
        for health_val in (self._restarts_val, self._last_exit_val, self._result_val):
            health_val.setText("-")
            health_val.setStyleSheet("")
        self._set_failed_row_visible(False)
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
        self._unit_file = None
        self._unit_reload_warning.hide()
        self._update_unit_buttons()
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
