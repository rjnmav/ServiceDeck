"""Main application window for ServiceDeck PySide6 client."""

import base64
import logging
from typing import Any

from PySide6.QtCore import QByteArray, QEvent, QItemSelection, QPoint, Qt, QTimer
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QSplitter,
    QTableView,
    QVBoxLayout,
    QWidget,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.remote import RemoteDevice
from servicedeck.api_client.models.service import (
    DaemonReloadResult,
    RevertResult,
    Service,
    ServiceEvent,
    ServiceOperationResult,
)
from servicedeck.gui.models.service_filter_model import ServiceFilterModel
from servicedeck.gui.models.service_model import ServiceTableModel
from servicedeck.gui.notifications import DesktopNotifier
from servicedeck.gui.preferences import GuiPreferences, GuiPreferencesStore, WatchedService
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import build_qpalette, get_palette, load_stylesheet
from servicedeck.gui.views.dialogs.add_remote_device_dialog import AddRemoteDeviceDialog
from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog
from servicedeck.gui.views.dialogs.edit_override_dialog import EditOverrideDialog
from servicedeck.gui.views.dialogs.manage_remote_devices_dialog import (
    ManageRemoteDevicesDialog,
)
from servicedeck.gui.views.dialogs.preferences_dialog import PreferencesDialog
from servicedeck.gui.views.dialogs.remote_onboarding import (
    LOCAL_TARGET,
    MAX_ONBOARDING_STEPS,
    connect_with_onboarding,
    handle_elevation_error,
    handle_onboarding_error,
    needs_elevation,
)
from servicedeck.gui.views.host_sidebar import HostSidebar
from servicedeck.gui.views.service_delegate import ServiceItemDelegate
from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel
from servicedeck.gui.views.service_toolbar import ServiceToolbar
from servicedeck.gui.watch_monitor import ServiceWatchMonitor, WatchKey
from servicedeck.gui.workers.service_worker import run_async_task
from servicedeck.gui.workers.stream_worker import StreamWorker

#: Reconnect delays (seconds) after the live update stream drops, growing per failure.
LIVE_RETRY_DELAYS = (2, 5, 10, 30, 60)
logger = logging.getLogger(__name__)


def _watch_sort_key(key: WatchKey) -> tuple[str, str, str]:
    return (key.device_id or "", key.scope, key.name)


class MainWindow(QMainWindow):
    """Master-detail main window with Host/Scope rail, filterable list, and right inspector."""

    def __init__(
        self,
        client: ServiceDeckClient,
        parent: Any = None,
        preferences_store: GuiPreferencesStore | None = None,
        notifier: DesktopNotifier | None = None,
    ) -> None:
        super().__init__(parent)
        self.client = client
        self._prefs_store = preferences_store or GuiPreferencesStore()
        prefs = self._prefs_store.load()
        self._notifier = notifier or DesktopNotifier()
        self._notify_on_failure: bool = prefs.notify_on_failure
        # Watched services: notified when they fail, on any host and scope.
        self._watch_monitor = ServiceWatchMonitor(client, self)
        self._watch_monitor.service_failed.connect(self._on_watched_service_failed)

        self._current_theme: str = prefs.theme
        self._current_scope = "user"
        self._current_device_id: str | None = None
        self._devices: list[RemoteDevice] = []
        self._is_busy = False
        self._onboarding_steps = 0
        # Hosts with a running administrator (root) agent, as last reported by the backend.
        # ``None`` stands for this computer (system unit file changes).
        self._elevated_devices: set[str | None] = set()
        self._log_refresh_interval: int = prefs.log_refresh_interval
        self._resource_refresh_interval: int = prefs.resource_refresh_interval
        self._window_maximized: bool = prefs.window_maximized
        self._saved_splitter_sizes: list[int] | None = prefs.splitter_sizes

        # Live updates: one event stream for the shown (device, scope).
        self._live_worker: StreamWorker | None = None
        self._live_key: tuple[str | None, str] | None = None
        self._live_connected = False
        self._live_failures = 0
        self._retired_workers: dict[int, StreamWorker] = {}
        self._live_retry_timer = QTimer(self)
        self._live_retry_timer.setSingleShot(True)
        self._live_retry_timer.timeout.connect(self._ensure_live_updates)
        self._resync_timer = QTimer(self)
        self._resync_timer.setSingleShot(True)
        self._resync_timer.setInterval(300)
        self._resync_timer.timeout.connect(self._refresh_in_place)

        self.setWindowTitle("Local System")
        self.setMinimumSize(980, 560)
        self.setWindowIcon(QIcon(":/assets/servicedeck.svg"))

        self._setup_menu_bar()
        self._setup_ui()
        self._restore_workspace_state(prefs)
        self._connect_signals()
        self._setup_shortcuts()
        self.apply_theme(self._current_theme)

        self._watch_monitor.set_watched(
            WatchKey(w.device_id, w.scope, w.name) for w in prefs.watched_services
        )
        self._refresh_watch_marks()
        self._initial_load()

    def _restore_workspace_state(self, prefs: GuiPreferences) -> None:
        """Apply persisted refresh intervals, window geometry, and splitter sizes."""
        self._detail_panel.set_refresh_intervals(
            self._log_refresh_interval, self._resource_refresh_interval
        )
        if prefs.window_geometry:
            try:
                raw = base64.b64decode(prefs.window_geometry.encode("ascii"))
                self.restoreGeometry(QByteArray(raw))
            except Exception:
                logger.warning("Ignoring invalid saved window geometry")
        if (
            prefs.splitter_sizes
            and len(prefs.splitter_sizes) == 2
            and all(s > 0 for s in prefs.splitter_sizes)
        ):
            self._splitter.setSizes(prefs.splitter_sizes)

    def show_initial(self) -> None:
        """Show the window respecting the saved maximized vs. normal geometry state."""
        if self._window_maximized:
            self.showMaximized()
        else:
            self.show()

    def _setup_menu_bar(self) -> None:
        menubar = QMenuBar(self)
        menubar.setNativeMenuBar(False)
        self.setMenuBar(menubar)

        file_menu = menubar.addMenu("&File")
        exit_action = file_menu.addAction("E&xit")
        app = QApplication.instance()
        if app is not None:
            exit_action.triggered.connect(app.quit)

        edit_menu = menubar.addMenu("&Edit")
        prefs_action = edit_menu.addAction("&Preferences")
        prefs_action.triggered.connect(self._on_preferences_clicked)

        help_menu = menubar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about_clicked)

        about_qt_action = help_menu.addAction("About &Qt")
        if app is not None:
            about_qt_action.triggered.connect(app.aboutQt)

        # Hidden by default, toggled via Alt key; Preferences & Theme live in the sidebar.
        menubar.hide()

    def _setup_ui(self) -> None:
        central = QWidget(self)
        root_layout = QHBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # ─── Left Host & Scope Rail ───
        self._sidebar = HostSidebar(self, theme=self._current_theme)
        root_layout.addWidget(self._sidebar)

        # ─── Workspace + Right Inspector Splitter ───
        self._splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._splitter.setChildrenCollapsible(False)

        workspace = QWidget(self._splitter)
        workspace_layout = QVBoxLayout(workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        self._toolbar = ServiceToolbar(workspace, is_dark=(self._current_theme == "dark"))
        workspace_layout.addWidget(self._toolbar)

        # Service Table & Models
        self._table_model = ServiceTableModel(self)
        self._filter_model = ServiceFilterModel(self)
        self._filter_model.setSourceModel(self._table_model)

        self._table_view = QTableView(workspace)
        self._table_view.setObjectName("serviceTable")
        self._table_view.setModel(self._filter_model)
        self._delegate = ServiceItemDelegate(self._table_view, theme=self._current_theme)
        self._table_view.setItemDelegate(self._delegate)
        self._table_view.setMouseTracking(True)
        self._table_view.setSortingEnabled(True)
        self._table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setShowGrid(False)
        self._table_view.verticalHeader().setVisible(False)
        self._table_view.verticalHeader().setDefaultSectionSize(ServiceItemDelegate.ROW_HEIGHT)

        h_header = self._table_view.horizontalHeader()
        h_header.setStretchLastSection(False)
        h_header.setSectionResizeMode(ServiceTableModel.COL_SERVICE, QHeaderView.ResizeMode.Stretch)
        h_header.setSectionResizeMode(ServiceTableModel.COL_STATUS, QHeaderView.ResizeMode.Fixed)
        h_header.setSectionResizeMode(ServiceTableModel.COL_STARTUP, QHeaderView.ResizeMode.Fixed)
        h_header.setHighlightSections(False)

        self._table_view.setColumnWidth(ServiceTableModel.COL_STATUS, 165)
        self._table_view.setColumnWidth(ServiceTableModel.COL_STARTUP, 145)
        self._table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table_view.sortByColumn(ServiceTableModel.COL_SERVICE, Qt.SortOrder.AscendingOrder)
        self._table_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._table_view.entered.connect(self._on_table_row_entered)
        self._table_view.viewport().installEventFilter(self)

        workspace_layout.addWidget(self._table_view, 1)
        self._splitter.addWidget(workspace)

        # Right-Side Inspector Drawer
        self._detail_panel = ServiceDetailPanel(
            self._splitter, client=self.client, theme=self._current_theme
        )
        self._splitter.addWidget(self._detail_panel)
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 2)
        self._splitter.setSizes([720, 440])
        self._detail_panel.hide()

        root_layout.addWidget(self._splitter, 1)
        self.setCentralWidget(central)

        # Status Bar
        status_bar = self.statusBar()
        if status_bar is not None:
            self._status_label = QLabel("Connecting to ServiceDeck backend...")
            self._status_label.setObjectName("statusMessage")
            self._count_label = QLabel("0 services")
            self._count_label.setObjectName("serviceCount")
            status_bar.addWidget(self._status_label, 1)
            status_bar.addPermanentWidget(self._count_label)
        else:
            self._status_label = QLabel()
            self._count_label = QLabel()

        self._set_live_indicator(False, "Live updates are not connected yet.")

    def _setup_shortcuts(self) -> None:
        search_shortcut = QShortcut(QKeySequence.StandardKey.Find, self)
        search_shortcut.activated.connect(self._toolbar.focus_search)

        self._toolbar.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        refresh_shortcut = QShortcut(QKeySequence(Qt.Key.Key_F5), self)
        refresh_shortcut.activated.connect(self.request_service_list)

        esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        esc_shortcut.activated.connect(self._on_escape_pressed)

    def _connect_signals(self) -> None:
        # Sidebar navigation
        self._sidebar.target_host_changed.connect(self._on_target_host_changed)
        self._sidebar.scope_toggled.connect(self._on_system_scope_toggled)
        self._sidebar.add_host_requested.connect(self._on_add_host_requested)
        self._sidebar.connect_host_requested.connect(self._on_connect_host_requested)
        self._sidebar.disconnect_host_requested.connect(self._on_disconnect_host_requested)
        self._sidebar.remove_host_requested.connect(self._on_remove_host_requested)
        self._sidebar.drop_admin_requested.connect(self._on_drop_admin_clicked)
        self._sidebar.reload_daemon_requested.connect(lambda: self._on_reload_daemon_clicked())
        self._sidebar.theme_toggle_requested.connect(self._on_toggle_theme)
        self._sidebar.preferences_requested.connect(self._on_preferences_clicked)

        # Workspace Header
        self._toolbar.refresh_requested.connect(self.request_service_list)
        self._toolbar.create_requested.connect(self._on_create_clicked)
        self._toolbar.search_text_changed.connect(self._filter_model.set_name_filter)
        self._toolbar.active_state_filter_changed.connect(
            self._filter_model.set_active_state_filter
        )

        # Right Inspector Drawer
        self._detail_panel.action_requested.connect(self._on_inspector_action)
        self._detail_panel.close_requested.connect(self._on_inspector_closed)
        self._detail_panel.edit_override_requested.connect(self._on_edit_override_requested)
        self._detail_panel.watch_toggled.connect(self._on_watch_toggled)
        self._detail_panel.revert_requested.connect(self._on_revert_requested)

        # Table Selection & Context Menu
        sel_model = self._table_view.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)
        self._table_view.customContextMenuRequested.connect(self._show_context_menu)

    def _initial_load(self) -> None:
        """Fetch scope, remote devices, and initial service list from backend."""

        def task() -> tuple[str, list[Service], list[RemoteDevice]]:
            scope_info = self.client.get_scope()
            try:
                devices = self.client.list_devices()
            except Exception:
                devices = []
            services = self.client.list_services(scope=scope_info.active_scope)
            return scope_info.active_scope, services, devices

        def on_success(result: tuple[str, list[Service], list[RemoteDevice]]) -> None:
            active_scope, services, devices = result
            self._current_scope = active_scope
            self._devices = devices
            self._sidebar.set_scope(active_scope)
            self._sidebar.set_hosts(devices, self._current_device_id)
            self._update_context_header()
            self._populate_table(services)
            self.set_status(f"Connected to backend ({active_scope} scope)", success=True)
            self._ensure_live_updates()
            self._sync_local_admin_state()

        def on_error(msg: str, exc: Any) -> None:
            self.set_status(f"Backend unavailable: {msg}", success=False)

        run_async_task(task, on_success=on_success, on_error=on_error)

    def request_service_list(self) -> None:
        """Fetch updated service list for the current scope and target host."""
        if self._is_busy:
            return

        device_id = self._current_device_id
        scope = self._current_scope

        def task() -> list[Service]:
            return self.client.list_services(scope=scope, device_id=device_id)

        def on_start() -> None:
            self._is_busy = True
            host_label = self._get_host_display_name()
            self.set_status(f"Refreshing {scope} services on {host_label}...")

        def on_success(services: list[Service]) -> None:
            self._is_busy = False
            self._onboarding_steps = 0
            self._populate_table(services)
            host_label = self._get_host_display_name()
            self.set_status(f"Loaded {len(services)} services ({host_label})", success=True)
            self._ensure_live_updates()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            if device_id is not None and self._onboarding_steps < MAX_ONBOARDING_STEPS:
                self._onboarding_steps += 1
                handled = handle_onboarding_error(
                    self,
                    self.client,
                    device_id,
                    exc,
                    target=self._device_target(device_id),
                    retry=self.request_service_list,
                    on_give_up=lambda reason: self.set_status(
                        f"Not connected to {self._get_host_display_name()}: {reason}",
                        success=False,
                    ),
                )
                if handled:
                    return
            self._onboarding_steps = 0
            self.set_status(f"Failed to refresh services: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _device_target(self, device_id: str) -> str:
        """``user@host`` label for prompts, from the known device list."""
        for dev in self._devices:
            if dev.id == device_id:
                return f"{dev.username}@{dev.hostname}" if dev.username else dev.hostname
        return device_id

    def _update_counts(self) -> None:
        counts = self._table_model.state_counts()
        self._toolbar.update_counts(counts)
        total = counts.get("all", 0)
        self._count_label.setText(f"{total} service{'s' if total != 1 else ''}")

    def _update_context_header(self) -> None:
        self._toolbar.set_context(self._get_host_display_name(), self._current_scope)
        self._update_window_title()
        self._refresh_watch_marks()

    def _populate_table(self, services: list[Service]) -> None:
        self._table_model.set_services(services)
        self._refresh_watch_marks()
        self._update_counts()
        self._detail_panel.clear()
        self._detail_panel.hide()

    def _on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        indexes = self._table_view.selectionModel().selectedRows()
        if not indexes:
            self._detail_panel.clear()
            self._detail_panel.hide()
            return

        source_index = self._filter_model.mapToSource(indexes[0])
        service = self._table_model.service_at(source_index.row())
        if service:
            self._detail_panel.show_service_details(
                service, scope=self._current_scope, device_id=self._current_device_id
            )
            self._detail_panel.set_watched(
                self._watch_monitor.is_watched(self._watch_key(service.name))
            )

    def _on_inspector_closed(self) -> None:
        self._detail_panel.clear()
        sel_model = self._table_view.selectionModel()
        if sel_model is not None:
            sel_model.clearSelection()

    def _on_escape_pressed(self) -> None:
        if self._detail_panel.isVisible():
            self._detail_panel.hide()
            self._on_inspector_closed()

    def _selected_service_name(self) -> str | None:
        indexes = self._table_view.selectionModel().selectedRows()
        if not indexes:
            return None
        source_index = self._filter_model.mapToSource(indexes[0])
        service = self._table_model.service_at(source_index.row())
        return service.name if service else None

    def _confirm_action(self, action: str, service_name: str) -> bool:
        reply = QMessageBox.warning(
            self,
            f"Confirm {action.capitalize()}",
            f"Are you sure you want to <b>{action}</b> the service:<br><br><b>{service_name}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _execute_service_op(
        self, op_name: str, fn: Any, *args: Any, name: str | None = None, _elevated: bool = False
    ) -> None:
        name = name or self._selected_service_name()
        if not name or self._is_busy:
            return

        device_id = self._current_device_id
        scope = self._current_scope

        def task() -> ServiceOperationResult:
            return fn(name, scope=scope, device_id=device_id)

        def on_start() -> None:
            self._is_busy = True
            self._detail_panel.set_actions_enabled(False)
            self.set_status(f"{op_name.capitalize()}ing '{name}'...")

        def on_success(res: ServiceOperationResult) -> None:
            self._is_busy = False
            msg = res.message or f"Service '{name}' {op_name}ed successfully."
            self.set_status(msg, success=True)
            self._detail_panel.set_actions_enabled(True)
            self._refresh_after_change()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            if device_id is not None and not _elevated and needs_elevation(exc):
                self._elevated_devices.discard(device_id)
                self._update_admin_indicator()
                self._detail_panel.set_actions_enabled(True)
                self._request_elevation(
                    device_id,
                    exc,
                    retry=lambda: self._execute_service_op(
                        op_name, fn, *args, name=name, _elevated=True
                    ),
                )
                return
            err_lower = msg.lower()
            if (
                "authentication" in err_lower
                or "authorization" in err_lower
                or "denied" in err_lower
                or "not authorized" in err_lower
            ):
                self.set_status(f"Permission denied {op_name}ing '{name}': {msg}", success=False)
            else:
                self.set_status(f"Error {op_name}ing '{name}': {msg}", success=False)
            self._detail_panel.set_actions_enabled(True)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _on_inspector_action(self, action: str) -> None:
        handlers = {
            "start": self._on_start_clicked,
            "stop": self._on_stop_clicked,
            "restart": self._on_restart_clicked,
            "enable": self._on_enable_clicked,
            "disable": self._on_disable_clicked,
            "reload": self._on_reload_clicked,
            "mask": self._on_mask_clicked,
            "unmask": self._on_unmask_clicked,
        }
        handler = handlers.get(action)
        if handler is not None:
            handler()

    def _on_start_clicked(self) -> None:
        self._execute_service_op("start", self.client.start_service)

    def _on_stop_clicked(self) -> None:
        name = self._selected_service_name()
        if name and self._confirm_action("stop", name):
            self._execute_service_op("stop", self.client.stop_service)

    def _on_restart_clicked(self) -> None:
        self._execute_service_op("restart", self.client.restart_service)

    def _on_enable_clicked(self) -> None:
        self._execute_service_op("enable", self.client.enable_service)

    def _on_disable_clicked(self) -> None:
        name = self._selected_service_name()
        if name and self._confirm_action("disable", name):
            self._execute_service_op("disable", self.client.disable_service)

    def _on_reload_clicked(self) -> None:
        self._execute_service_op("reload", self.client.reload_service)

    def _on_mask_clicked(self) -> None:
        name = self._selected_service_name()
        if name and self._confirm_action("mask", name):
            self._execute_service_op("mask", self.client.mask_service)

    def _on_unmask_clicked(self) -> None:
        name = self._selected_service_name()
        if name and self._confirm_action("unmask", name):
            self._execute_service_op("unmask", self.client.unmask_service)

    def _on_reload_daemon_clicked(self, _elevated: bool = False) -> None:
        if self._is_busy:
            return

        device_id = self._current_device_id
        scope = self._current_scope

        def task() -> DaemonReloadResult:
            return self.client.reload_daemon(scope=scope, device_id=device_id)

        def on_start() -> None:
            self._is_busy = True
            self.set_status(f"Reloading systemd daemon ({scope} scope)...")

        def on_success(res: DaemonReloadResult) -> None:
            self._is_busy = False
            self.set_status(res.message or "Daemon reloaded successfully.", success=True)
            self._refresh_after_change()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            if device_id is not None and not _elevated and needs_elevation(exc):
                self._request_elevation(
                    device_id, exc, retry=lambda: self._on_reload_daemon_clicked(_elevated=True)
                )
                return
            self.set_status(f"Failed to reload daemon: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _on_create_clicked(self) -> None:
        dlg = CreateServiceDialog(
            self,
            client=self.client,
            default_scope=self._current_scope,
            device_id=self._current_device_id,
            target=(
                self._device_target(self._current_device_id)
                if self._current_device_id is not None
                else None
            ),
            on_elevated=self._mark_current_device_elevated,
        )
        if dlg.exec():
            self.request_service_list()

    # --- Unit file overrides (drop-ins) ---

    def _on_edit_override_requested(self) -> None:
        unit = self._detail_panel.current_unit_file
        if unit is None or self._is_busy:
            return
        device_id = self._detail_panel.current_device_id
        dlg = EditOverrideDialog(
            self,
            client=self.client,
            unit=unit,
            scope=self._detail_panel.current_scope,
            device_id=device_id,
            target=self._device_target(device_id) if device_id is not None else LOCAL_TARGET,
            on_elevated=self._mark_current_device_elevated,
        )
        if not dlg.exec():
            return
        result = dlg.result_override
        if result is not None:
            if result.removed:
                self.set_status(f"Removed {result.path}; systemd reloaded.", success=True)
            else:
                note = f" ({len(result.warnings)} warning(s))" if result.warnings else ""
                self.set_status(f"Saved {result.path}; systemd reloaded{note}.", success=True)
        self._detail_panel.refresh_unit_file()
        self._refresh_after_change()

    def _on_revert_requested(self) -> None:
        unit = self._detail_panel.current_unit_file
        if unit is None or self._is_busy or not unit.editable_drop_ins:
            return
        files = "<br>".join(f"<code>{d.path}</code>" for d in unit.editable_drop_ins)
        reply = QMessageBox.warning(
            self,
            "Revert to Vendor Configuration",
            f"Remove the overrides of <b>{unit.service}</b>?<br><br>"
            f"These files will be deleted:<br>{files}<br><br>"
            "systemd is reloaded afterwards. A running service keeps its current settings "
            "until it is restarted.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._revert_overrides(
            unit.service, self._detail_panel.current_scope, self._detail_panel.current_device_id
        )

    def _revert_overrides(
        self, name: str, scope: str, device_id: str | None, *, _elevated: bool = False
    ) -> None:
        def task() -> RevertResult:
            return self.client.revert_overrides(name, scope=scope, device_id=device_id)

        def on_start() -> None:
            self._is_busy = True
            self._detail_panel.set_actions_enabled(False)
            self.set_status(f"Reverting '{name}' to its vendor configuration...")

        def on_success(result: RevertResult) -> None:
            self._is_busy = False
            self._detail_panel.set_actions_enabled(True)
            count = len(result.removed_paths)
            self.set_status(
                f"Removed {count} override file(s) of '{name}'; systemd reloaded.", success=True
            )
            self._detail_panel.refresh_unit_file()
            self._refresh_after_change()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            self._detail_panel.set_actions_enabled(True)
            if not _elevated and needs_elevation(exc):
                self._request_elevation(
                    device_id,
                    exc,
                    retry=lambda: self._revert_overrides(name, scope, device_id, _elevated=True),
                )
                return
            self.set_status(f"Failed to revert '{name}': {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _on_system_scope_toggled(self, is_system: bool) -> None:
        new_scope = "system" if is_system else "user"
        if new_scope == self._current_scope:
            return
        if self._is_busy:
            self._sidebar.set_scope(self._current_scope)
            return

        self._detail_panel.clear()
        self._detail_panel.hide()
        if self._table_view.selectionModel():
            self._table_view.selectionModel().clearSelection()
        self._toolbar.clear_filters()

        device_id = self._current_device_id

        def task() -> tuple[str, list[Service]]:
            if device_id is None:
                scope_info = self.client.set_scope(new_scope)
                active_scope = scope_info.active_scope
            else:
                active_scope = new_scope
            services = self.client.list_services(scope=active_scope, device_id=device_id)
            return active_scope, services

        def on_start() -> None:
            self._is_busy = True
            self._sidebar.set_scope_enabled(False)
            self.set_status(f"Switching to {new_scope} scope...")

        def on_success(result: tuple[str, list[Service]]) -> None:
            self._is_busy = False
            self._sidebar.set_scope_enabled(True)
            active_scope, services = result
            self._current_scope = active_scope
            self._sidebar.set_scope(active_scope)
            self._update_context_header()
            self._populate_table(services)
            self.set_status(
                f"Switched to {active_scope} scope ({len(services)} services)", success=True
            )
            self._ensure_live_updates()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            self._sidebar.set_scope_enabled(True)
            self._sidebar.set_scope(self._current_scope)
            self.set_status(f"Failed to switch scope: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    # --- Live updates ---

    @property
    def _live_label(self) -> QLabel:
        return self._toolbar.live_label

    @property
    def live_updates_connected(self) -> bool:
        """True while the event stream for the shown host and scope is open."""
        return self._live_connected

    def _ensure_live_updates(self) -> None:
        """Watch the shown (device, scope) for changes, replacing any other stream."""
        key = (self._current_device_id, self._current_scope)
        if self._live_worker is not None and self._live_key == key:
            return
        self._stop_live_updates()
        self._live_retry_timer.stop()
        self._live_key = key
        device_id, scope = key
        client = self.client
        worker = StreamWorker(
            lambda: client.watch_services(scope=scope, device_id=device_id), name="events"
        )
        worker.signals.item.connect(self._on_live_event)
        worker.signals.failed.connect(self._on_live_failed)
        worker.signals.finished.connect(self._on_live_finished)
        self._live_worker = worker
        worker.start()

    def _stop_live_updates(self) -> None:
        worker, self._live_worker = self._live_worker, None
        self._live_key = None
        if worker is not None:
            worker.stop()
            self._retired_workers[worker.token] = worker
        self._set_live_indicator(False, "Live updates stopped.")

    def _is_current_live_worker(self, token: int) -> bool:
        return self._live_worker is not None and self._live_worker.token == token

    def _set_live_indicator(self, connected: bool, tooltip: str) -> None:
        self._live_connected = connected
        self._toolbar.set_live_status(connected, tooltip)

    def _on_live_event(self, token: int, event: ServiceEvent) -> None:
        if not self._is_current_live_worker(token):
            return
        if event.kind == "ready":
            self._live_failures = 0
            self._set_live_indicator(
                True, "Live updates on: the list follows changes as systemd reports them."
            )
            self._resync_timer.start()
        elif event.kind == "resync":
            self._resync_timer.start()
        elif event.kind == "changed" and event.service is not None:
            self._apply_live_change(event.service)
        elif event.kind == "removed" and event.name:
            self._table_model.remove_service(event.name)
            self._update_counts()

    def _apply_live_change(self, service: Service) -> None:
        previous, current = self._table_model.apply_service_change(service)
        self._update_counts()
        if current.is_failed and (previous is None or not previous.is_failed):
            self.set_status(f"Alert: {current.name} failed ({current.sub_state})", success=False)
        if self._selected_service_name() == current.name:
            self._detail_panel.update_service_state(current)

    def _on_live_failed(self, token: int, message: str, exc: Any) -> None:
        if not self._is_current_live_worker(token):
            return
        self._live_worker = None
        self._schedule_live_retry(f"Live updates unavailable: {message}")

    def _on_live_finished(self, token: int) -> None:
        self._retired_workers.pop(token, None)
        if self._is_current_live_worker(token):
            self._live_worker = None
            self._schedule_live_retry("Live updates ended; reconnecting.")

    def _schedule_live_retry(self, reason: str) -> None:
        delay = LIVE_RETRY_DELAYS[min(self._live_failures, len(LIVE_RETRY_DELAYS) - 1)]
        self._live_failures += 1
        self._live_key = None
        self._set_live_indicator(False, f"{reason}\nRetrying in {delay}s.")
        self._live_retry_timer.start(delay * 1000)

    def _refresh_after_change(self) -> None:
        """After an action: update rows in place if live, else reload the list."""
        if self._live_connected:
            self._refresh_in_place()
        else:
            self.request_service_list()

    def _refresh_in_place(self) -> None:
        """Re-list services and merge them into the table, keeping the selection."""
        device_id, scope = self._current_device_id, self._current_scope

        def on_success(services: list[Service]) -> None:
            if (device_id, scope) != (self._current_device_id, self._current_scope):
                return
            self._table_model.merge_services(services)
            self._update_counts()
            name = self._selected_service_name()
            service = self._table_model.service_by_name(name) if name else None
            if service is not None:
                self._detail_panel.update_service_state(service)

        run_async_task(
            self.client.list_services,
            scope=scope,
            device_id=device_id,
            on_success=on_success,
            on_error=lambda msg, _exc: None,
        )

    def closeEvent(self, event: Any) -> None:
        """Persist workspace preferences and close live streams before exit."""
        self._save_preferences(include_layout=True)
        self._live_retry_timer.stop()
        self._stop_live_updates()
        self._watch_monitor.stop()
        self._detail_panel.stop_timers()
        super().closeEvent(event)

    def _get_host_display_name(self) -> str:
        """Return human-readable display name of currently active host target."""
        if self._current_device_id is None:
            return "Local System"
        for dev in self._devices:
            if dev.id == self._current_device_id:
                return f"{dev.display_name} ({dev.hostname})"
        return f"Host ({self._current_device_id})"

    def _update_window_title(self) -> None:
        """Update window title cleanly without duplicating applicationDisplayName."""
        self.setWindowTitle(self._get_host_display_name())

    def _request_elevation(self, device_id: str | None, exc: Any, *, retry: Any) -> None:
        """Get administrator access on ``device_id`` (asking for sudo), then ``retry``.

        ``device_id=None`` means this computer (system unit file changes).
        """
        where = "this computer" if device_id is None else self._get_host_display_name()
        self.set_status(f"Requesting administrator access on {where}...")
        self._elevated_devices.discard(device_id)
        self._update_admin_indicator()

        def elevated() -> None:
            self._elevated_devices.add(device_id)
            self._update_admin_indicator()

        handle_elevation_error(
            self,
            self.client,
            device_id,
            exc,
            target=self._device_target(device_id) if device_id is not None else LOCAL_TARGET,
            retry=retry,
            on_give_up=lambda reason: self.set_status(
                f"Administrator access not granted: {reason}", success=False
            ),
            on_elevated=elevated,
        )

    def _mark_current_device_elevated(self) -> None:
        self._elevated_devices.add(self._current_device_id)
        self._update_admin_indicator()

    def _update_admin_indicator(self) -> None:
        device_id = self._current_device_id
        button = self._sidebar.admin_button
        button.setVisible(device_id in self._elevated_devices)
        if device_id is None:
            button.setToolTip(
                "System unit files on this computer are changed with administrator access.\n"
                "Click to drop administrator privileges."
            )
        else:
            button.setToolTip(
                "System services on this remote host use administrator access.\n"
                "Click to drop administrator privileges."
            )

    def _sync_local_admin_state(self) -> None:
        """Ask the backend whether this computer's admin session is still running.

        It ends by itself after a while without use, so the indicator is refreshed when
        the local host is shown.
        """

        def on_success(elevated: Any) -> None:
            if elevated is True:
                self._elevated_devices.add(None)
            else:
                self._elevated_devices.discard(None)
            self._update_admin_indicator()

        run_async_task(
            self.client.get_local_elevation,
            on_success=on_success,
            on_error=lambda _msg, _exc: None,
        )

    def _on_drop_admin_clicked(self) -> None:
        device_id = self._current_device_id

        def done(_result: Any = None) -> None:
            self._elevated_devices.discard(device_id)
            self._update_admin_indicator()
            self.set_status("Administrator access dropped.", success=True)

        if device_id is None:
            run_async_task(
                self.client.drop_local_elevation,
                on_success=done,
                on_error=lambda msg, _exc: self.set_status(
                    f"Failed to drop administrator access: {msg}", success=False
                ),
            )
            return

        run_async_task(
            self.client.drop_device_privileges,
            device_id,
            on_success=done,
            on_error=lambda msg, _exc: self.set_status(
                f"Failed to drop administrator access: {msg}", success=False
            ),
        )

    def _on_target_host_changed(self, device_id: str | None) -> None:
        """Switch target host and refresh service inventory."""
        if device_id != self._current_device_id:
            self._toolbar.clear_filters()
        self._current_device_id = device_id
        self._stop_live_updates()
        self._live_retry_timer.stop()
        self._live_failures = 0
        self._update_admin_indicator()
        if device_id is None:
            self._sync_local_admin_state()
        self._update_context_header()
        self._detail_panel.clear()
        self._detail_panel.hide()
        self.request_service_list()

    def _on_add_host_requested(self) -> None:
        """Show Add Remote Host dialog and switch to it upon creation."""
        dlg = AddRemoteDeviceDialog(self, client=self.client)
        if dlg.exec():
            new_id = dlg.created_device.id if dlg.created_device else None
            self._refresh_hosts_list(switch_to_id=new_id)

    def _on_connect_host_requested(self, device_id: str) -> None:
        """Connect to a remote host directly from the sidebar host menu."""

        def on_success(_info: Any) -> None:
            self.set_status(f"Connected to {self._device_target(device_id)}.", success=True)
            self._refresh_hosts_list(switch_to_id=device_id)

        def on_error(msg: str, _exc: Any) -> None:
            self.set_status(f"Failed to connect: {msg}", success=False)
            self._refresh_hosts_list()

        connect_with_onboarding(
            self,
            self.client,
            device_id,
            target=self._device_target(device_id),
            on_success=on_success,
            on_error=on_error,
        )

    def _on_disconnect_host_requested(self, device_id: str) -> None:
        """Disconnect a remote host directly from the sidebar host menu."""

        def on_success(_res: Any = None) -> None:
            self.set_status("Disconnected remote host.", success=True)
            self._refresh_hosts_list()

        run_async_task(
            self.client.disconnect_device,
            device_id,
            on_success=on_success,
            on_error=lambda msg, _exc: self.set_status(
                f"Failed to disconnect host: {msg}", success=False
            ),
        )

    def _on_remove_host_requested(self, device_id: str) -> None:
        """Confirm and remove a remote host directly from the sidebar host menu."""
        reply = QMessageBox.question(
            self,
            "Remove Remote Host",
            f"Remove remote host <b>{device_id}</b> from ServiceDeck?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        def on_success(_res: Any = None) -> None:
            self.set_status(f"Removed host '{device_id}'.", success=True)
            next_id = None if self._current_device_id == device_id else self._current_device_id
            self._refresh_hosts_list(switch_to_id=next_id)

        run_async_task(
            self.client.remove_device,
            device_id,
            on_success=on_success,
            on_error=lambda msg, _exc: self.set_status(
                f"Failed to remove host: {msg}", success=False
            ),
        )

    def _on_manage_hosts_requested(self) -> None:
        """Show Manage Remote Hosts dialog and handle switch or update."""
        dlg = ManageRemoteDevicesDialog(self, client=self.client)
        dlg.exec()
        target_id = dlg.selected_device_id if dlg.selected_device_id else self._current_device_id
        self._refresh_hosts_list(switch_to_id=target_id)

    def _refresh_hosts_list(self, switch_to_id: str | None = None) -> None:
        """Reload remote devices list from backend and update sidebar."""

        def task() -> list[RemoteDevice]:
            return self.client.list_devices()

        def on_success(devices: list[RemoteDevice]) -> None:
            self._devices = devices
            target_id = switch_to_id if switch_to_id is not None else self._current_device_id
            if target_id is not None and not any(d.id == target_id for d in devices):
                target_id = None

            if target_id != self._current_device_id:
                self._toolbar.clear_filters()
            self._current_device_id = target_id
            self._update_admin_indicator()
            self._update_context_header()
            self._sidebar.set_hosts(devices, self._current_device_id)
            self._detail_panel.clear()
            self._detail_panel.hide()
            self.request_service_list()

        def on_error(msg: str, exc: Any) -> None:
            self.set_status(f"Failed to refresh hosts list: {msg}", success=False)

        run_async_task(task, on_success=on_success, on_error=on_error)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self._table_view.indexAt(pos)
        if not index.isValid():
            return

        self._table_view.selectRow(index.row())
        palette = get_palette(self._current_theme)

        menu = QMenu(self)
        menu.setObjectName("contextMenu")

        menu.addAction(
            IconHelper.svg_icon("play", palette.success_text),
            "Start",
            self._on_start_clicked,
        )
        menu.addAction(
            IconHelper.svg_icon("stop", palette.danger_text),
            "Stop",
            self._on_stop_clicked,
        )
        menu.addAction(
            IconHelper.svg_icon("restart", palette.text_primary),
            "Restart",
            self._on_restart_clicked,
        )
        menu.addSeparator()
        menu.addAction(
            IconHelper.svg_icon("check", palette.success_text),
            "Enable",
            self._on_enable_clicked,
        )
        menu.addAction(
            IconHelper.svg_icon("ban", palette.danger_text),
            "Disable",
            self._on_disable_clicked,
        )
        menu.addSeparator()
        menu.addAction(
            IconHelper.svg_icon("lock", palette.masked_text),
            "Mask",
            self._on_mask_clicked,
        )
        menu.addAction(
            IconHelper.svg_icon("unlock", palette.success_text),
            "Unmask",
            self._on_unmask_clicked,
        )

        menu.addSeparator()
        name = self._selected_service_name()
        if name:
            key = self._watch_key(name)
            watch_action = menu.addAction(
                IconHelper.svg_icon("bell", palette.warning_text), "Notify on Failure"
            )
            watch_action.setCheckable(True)
            watch_action.setChecked(self._watch_monitor.is_watched(key))
            watch_action.toggled.connect(lambda checked, k=key: self._set_watched(k, checked))

        global_pos = self._table_view.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

    # --- Watched services (notify on failure) ---

    def _watch_key(self, name: str) -> WatchKey:
        return WatchKey(self._current_device_id, self._current_scope, name)

    def _refresh_watch_marks(self) -> None:
        """Show the bell on watched rows of the host and scope on screen."""
        group = (self._current_device_id, self._current_scope)
        self._table_model.set_watched_names(
            {k.name for k in self._watch_monitor.watched if k.group == group}
        )

    def _on_watch_toggled(self, checked: bool) -> None:
        service = self._detail_panel.current_service
        if service is None:
            return
        key = WatchKey(
            self._detail_panel.current_device_id, self._detail_panel.current_scope, service.name
        )
        self._set_watched(key, checked)

    def _set_watched(self, key: WatchKey, watched: bool) -> None:
        if watched == self._watch_monitor.is_watched(key):
            return
        if watched:
            self._watch_monitor.watch(key)
            self.set_status(f"You will be notified if {key.name} fails.", success=True)
        else:
            self._watch_monitor.unwatch(key)
            self.set_status(f"Stopped watching {key.name}.")
        self._refresh_watch_marks()
        current = self._detail_panel.current_service
        if current is not None and current.name == key.name:
            self._detail_panel.set_watched(
                self._watch_monitor.is_watched(self._watch_key(key.name))
            )
        self._save_preferences()

    def _host_label(self, device_id: str | None) -> str:
        if device_id is None:
            return "this computer"
        for dev in self._devices:
            if dev.id == device_id:
                return dev.display_name or dev.hostname
        return device_id

    def _on_watched_service_failed(self, key: WatchKey, service: Service) -> None:
        where = f"{self._host_label(key.device_id)}, {key.scope} scope"
        summary = f"{service.name} failed"
        body = f"{service.description or service.name} on {where} ({service.sub_state})."
        self.set_status(f"Alert: {service.name} failed on {where}", success=False)
        QApplication.alert(self)
        if self._notify_on_failure:
            self._notifier.notify(
                summary,
                body,
                on_failed=lambda reason: logger.info("No desktop notification: %s", reason),
            )

    def set_status(self, message: str, success: bool | None = None) -> None:
        """Update status bar label and styling."""
        palette = get_palette(self._current_theme)
        self._status_label.setText(message)
        if success is True:
            self._status_label.setStyleSheet(f"color: {palette.success_text}; font-weight: 600;")
        elif success is False:
            self._status_label.setStyleSheet(f"color: {palette.danger_text}; font-weight: 600;")
        else:
            self._status_label.setStyleSheet("")

    def _save_preferences(self, *, include_layout: bool = False) -> None:
        """Persist current theme, intervals, and optionally window layout."""
        theme = "light" if self._current_theme == "light" else "dark"
        existing = self._prefs_store.load()
        geometry_b64 = existing.window_geometry
        maximized = existing.window_maximized
        splitter_sizes = existing.splitter_sizes

        if include_layout:
            maximized = self.isMaximized()
            if not maximized:
                geometry_b64 = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
            if self._detail_panel.isVisible():
                sizes = self._splitter.sizes()
                if len(sizes) == 2 and all(s > 0 for s in sizes):
                    splitter_sizes = sizes

        prefs = GuiPreferences(
            theme=theme,  # type: ignore[arg-type]
            log_refresh_interval=max(1, min(60, self._log_refresh_interval)),
            resource_refresh_interval=max(1, min(60, self._resource_refresh_interval)),
            window_maximized=maximized,
            window_geometry=geometry_b64,
            splitter_sizes=splitter_sizes,
            watched_services=[
                WatchedService(device_id=k.device_id, scope=k.scope, name=k.name)  # type: ignore[arg-type]
                for k in sorted(self._watch_monitor.watched, key=_watch_sort_key)
            ],
            notify_on_failure=self._notify_on_failure,
        )
        try:
            self._prefs_store.save(prefs)
        except Exception as exc:
            logger.warning("Could not persist GUI preferences: %s", exc)

    def _on_toggle_theme(self) -> None:
        next_theme = "light" if self._current_theme == "dark" else "dark"
        self.apply_theme(next_theme)
        self._save_preferences()

    def apply_theme(self, theme: str) -> None:
        """Apply dark or light theme palette, stylesheet, icons, and delegates."""
        self._current_theme = theme
        qpalette = build_qpalette(theme)
        app = QApplication.instance()
        if app is not None:
            app.setPalette(qpalette)
        self.setPalette(qpalette)

        stylesheet = load_stylesheet(theme)
        if stylesheet:
            if app is not None:
                app.setStyleSheet(stylesheet)
                self.setStyleSheet("")
            else:
                self.setStyleSheet(stylesheet)

        self._sidebar.refresh_theme(theme)
        self._toolbar.refresh_icons(is_dark=(theme == "dark"))
        self._detail_panel.refresh_theme(theme)
        self._delegate.set_theme(theme)
        self._set_live_indicator(
            self._live_connected,
            self._toolbar.live_label.toolTip(),
        )
        self._table_view.viewport().update()

    def _on_table_row_entered(self, index: Any) -> None:
        self._delegate.set_hovered_row(index.row() if index.isValid() else -1)
        self._table_view.viewport().update()

    def eventFilter(self, obj: Any, event: Any) -> bool:
        if obj is self._table_view.viewport() and event.type() == QEvent.Type.Leave:
            self._delegate.set_hovered_row(-1)
            self._table_view.viewport().update()
        return super().eventFilter(obj, event)

    def _on_preferences_clicked(self) -> None:
        dlg = PreferencesDialog(
            current_theme=self._current_theme,
            log_interval=self._log_refresh_interval,
            res_interval=self._resource_refresh_interval,
            parent=self,
            notify_on_failure=self._notify_on_failure,
        )
        dlg.notifications_changed.connect(self._on_notifications_pref_changed)
        dlg.preferences_changed.connect(self._on_preferences_updated)
        dlg.exec()

    def _on_notifications_pref_changed(self, enabled: bool) -> None:
        self._notify_on_failure = enabled

    def _on_preferences_updated(self, theme: str, log_int: int, res_int: int) -> None:
        self._log_refresh_interval = log_int
        self._resource_refresh_interval = res_int
        self.apply_theme(theme)
        self._detail_panel.set_refresh_intervals(log_int, res_int)
        self._save_preferences()

    def _on_about_clicked(self) -> None:
        QMessageBox.about(
            self,
            "About ServiceDeck",
            "<b>ServiceDeck 2.0</b><br><br>"
            "A modern Linux desktop application for managing "
            "systemd services.<br><br>"
            "Version 2.0.0<br>",
        )

    def keyPressEvent(self, event: Any) -> None:
        """Toggle menubar visibility when the Alt key is pressed."""
        if event.key() == Qt.Key.Key_Alt:
            menubar = self.menuBar()
            if menubar is not None:
                menubar.setVisible(not menubar.isVisible())
        super().keyPressEvent(event)
