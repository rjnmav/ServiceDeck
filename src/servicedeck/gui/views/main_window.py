"""Main application window for ServiceDeck PySide6 client."""

from typing import Any

from PySide6.QtCore import QEvent, QItemSelection, QPoint, Qt, QTimer
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
    Service,
    ServiceEvent,
    ServiceOperationResult,
)
from servicedeck.gui.models.service_filter_model import ServiceFilterModel
from servicedeck.gui.models.service_model import ServiceTableModel
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import build_qpalette, get_palette, load_stylesheet
from servicedeck.gui.views.dialogs.add_remote_device_dialog import AddRemoteDeviceDialog
from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog
from servicedeck.gui.views.dialogs.manage_remote_devices_dialog import (
    ManageRemoteDevicesDialog,
)
from servicedeck.gui.views.dialogs.preferences_dialog import PreferencesDialog
from servicedeck.gui.views.dialogs.remote_onboarding import (
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
from servicedeck.gui.workers.service_worker import run_async_task
from servicedeck.gui.workers.stream_worker import StreamWorker

#: Reconnect delays (seconds) after the live update stream drops, growing per failure.
LIVE_RETRY_DELAYS = (2, 5, 10, 30, 60)


class MainWindow(QMainWindow):
    """Master-detail main window with Host/Scope rail, filterable list, and right inspector."""

    def __init__(self, client: ServiceDeckClient, parent: Any = None) -> None:
        super().__init__(parent)
        self.client = client
        self._current_theme = "dark"
        self._current_scope = "user"
        self._current_device_id: str | None = None
        self._devices: list[RemoteDevice] = []
        self._is_busy = False
        self._onboarding_steps = 0
        # Devices with a running administrator (root) agent, as last reported by the backend.
        self._elevated_devices: set[str] = set()
        self._log_refresh_interval = 5
        self._resource_refresh_interval = 2

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
        self._connect_signals()
        self._setup_shortcuts()
        self.apply_theme(self._current_theme)

        self._initial_load()

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

    def _populate_table(self, services: list[Service]) -> None:
        self._table_model.set_services(services)
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
        """Close live streams before the window goes away."""
        self._live_retry_timer.stop()
        self._stop_live_updates()
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

    def _request_elevation(self, device_id: str, exc: Any, *, retry: Any) -> None:
        """Get administrator access on ``device_id`` (asking for sudo), then ``retry``."""
        self.set_status(f"Requesting administrator access on {self._get_host_display_name()}...")

        def elevated() -> None:
            self._elevated_devices.add(device_id)
            self._update_admin_indicator()

        handle_elevation_error(
            self,
            self.client,
            device_id,
            exc,
            target=self._device_target(device_id),
            retry=retry,
            on_give_up=lambda reason: self.set_status(
                f"Administrator access not granted: {reason}", success=False
            ),
            on_elevated=elevated,
        )

    def _mark_current_device_elevated(self) -> None:
        if self._current_device_id is not None:
            self._elevated_devices.add(self._current_device_id)
            self._update_admin_indicator()

    def _update_admin_indicator(self) -> None:
        device_id = self._current_device_id
        self._sidebar.admin_button.setVisible(
            device_id is not None and device_id in self._elevated_devices
        )

    def _on_drop_admin_clicked(self) -> None:
        device_id = self._current_device_id
        if device_id is None:
            return

        def done(_result: Any = None) -> None:
            self._elevated_devices.discard(device_id)
            self._update_admin_indicator()
            self.set_status("Administrator access dropped.", success=True)

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
        self._current_device_id = device_id
        self._stop_live_updates()
        self._live_retry_timer.stop()
        self._live_failures = 0
        self._update_admin_indicator()
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

        global_pos = self._table_view.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

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

    def _on_toggle_theme(self) -> None:
        next_theme = "light" if self._current_theme == "dark" else "dark"
        self.apply_theme(next_theme)

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
        )
        dlg.preferences_changed.connect(self._on_preferences_updated)
        dlg.exec()

    def _on_preferences_updated(self, theme: str, log_int: int, res_int: int) -> None:
        self._log_refresh_interval = log_int
        self._resource_refresh_interval = res_int
        self.apply_theme(theme)
        self._detail_panel.set_refresh_intervals(log_int, res_int)

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
