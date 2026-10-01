"""Main application window for ServiceDeck PySide6 client."""

from typing import Any

from PySide6.QtCore import QFile, QItemSelection, QPoint, Qt
from PySide6.QtGui import QColor, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMenu,
    QMenuBar,
    QMessageBox,
    QTableView,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import (
    DaemonReloadResult,
    Service,
    ServiceOperationResult,
)
from servicedeck.gui.models.service_filter_model import ServiceFilterModel
from servicedeck.gui.models.service_model import ServiceTableModel
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.views.dialogs.create_service_dialog import CreateServiceDialog
from servicedeck.gui.views.dialogs.preferences_dialog import PreferencesDialog
from servicedeck.gui.views.service_detail_panel import ServiceDetailPanel
from servicedeck.gui.views.service_toolbar import ServiceToolbar
from servicedeck.gui.workers.service_worker import run_async_task


class MainWindow(QMainWindow):
    """Main window faithfully recreating the original ServiceDeck C++/Qt user interface."""

    def __init__(self, client: ServiceDeckClient, parent: Any = None) -> None:
        super().__init__(parent)
        self.client = client
        self._current_theme = "dark"
        self._current_scope = "user"
        self._is_busy = False
        self._log_refresh_interval = 5
        self._resource_refresh_interval = 2

        self.setWindowTitle("ServiceDeck — Systemd Service Manager")
        self.setMinimumSize(900, 500)
        self.setWindowIcon(QIcon(":/assets/servicedeck.svg"))

        self._setup_menu_bar()
        self._setup_ui()
        self._connect_signals()
        self.apply_theme(self._current_theme)

        # Initial scope and service list fetch
        self._initial_load()

    def _setup_menu_bar(self) -> None:
        menubar = QMenuBar(self)
        menubar.setNativeMenuBar(False)
        self.setMenuBar(menubar)

        # File Menu
        file_menu = menubar.addMenu("&File")
        exit_action = file_menu.addAction("E&xit")
        app = QApplication.instance()
        if app is not None:
            exit_action.triggered.connect(app.quit)

        # Edit Menu
        edit_menu = menubar.addMenu("&Edit")
        prefs_action = edit_menu.addAction("&Preferences")
        prefs_action.triggered.connect(self._on_preferences_clicked)

        # Help Menu
        help_menu = menubar.addMenu("&Help")
        about_action = help_menu.addAction("&About")
        about_action.triggered.connect(self._on_about_clicked)

        about_qt_action = help_menu.addAction("About &Qt")
        if app is not None:
            about_qt_action.triggered.connect(app.aboutQt)

        # Hidden by default, toggled via Alt key
        menubar.hide()

    def _setup_ui(self) -> None:
        # Toolbar
        self._toolbar = ServiceToolbar(self, is_dark=(self._current_theme == "dark"))
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self._toolbar)

        # Service Table & Models
        self._table_model = ServiceTableModel(self)
        self._filter_model = ServiceFilterModel(self)
        self._filter_model.setSourceModel(self._table_model)

        self._table_view = QTableView(self)
        self._table_view.setObjectName("serviceTable")
        self._table_view.setModel(self._filter_model)
        self._table_view.setSortingEnabled(True)
        self._table_view.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table_view.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table_view.setAlternatingRowColors(True)
        self._table_view.setShowGrid(False)
        self._table_view.verticalHeader().setVisible(False)

        h_header = self._table_view.horizontalHeader()
        h_header.setStretchLastSection(True)
        h_header.setSectionResizeMode(0, QHeaderView.ResizeMode.Interactive)
        h_header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        h_header.setHighlightSections(False)

        self._table_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table_view.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self._table_view.setFocusPolicy(Qt.FocusPolicy.NoFocus)

        self._table_view.setColumnWidth(0, 350)
        self._table_view.setColumnWidth(2, 150)
        self._table_view.setColumnWidth(3, 150)
        self._table_view.setColumnWidth(4, 150)

        self.setCentralWidget(self._table_view)

        # Bottom Detail Panel Dock
        self._detail_panel = ServiceDetailPanel(self, client=self.client)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self._detail_panel)
        self._detail_panel.hide()

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

    def _connect_signals(self) -> None:
        # Toolbar actions
        self._toolbar.start_action.triggered.connect(self._on_start_clicked)
        self._toolbar.stop_action.triggered.connect(self._on_stop_clicked)
        self._toolbar.restart_action.triggered.connect(self._on_restart_clicked)
        self._toolbar.enable_action.triggered.connect(self._on_enable_clicked)
        self._toolbar.disable_action.triggered.connect(self._on_disable_clicked)
        self._toolbar.mask_action.triggered.connect(self._on_mask_clicked)
        self._toolbar.unmask_action.triggered.connect(self._on_unmask_clicked)
        self._toolbar.reload_action.triggered.connect(self._on_reload_daemon_clicked)

        self._toolbar.refresh_action.setShortcut(QKeySequence.StandardKey.Refresh)
        self._toolbar.refresh_action.triggered.connect(self.request_service_list)
        self._toolbar.create_action.triggered.connect(self._on_create_clicked)

        # Search & Filter
        self._toolbar.search_text_changed.connect(self._filter_model.set_name_filter)
        self._toolbar.active_state_filter_changed.connect(
            self._filter_model.set_active_state_filter
        )
        self._toolbar.system_mode_toggled.connect(self._on_system_scope_toggled)

        # Table Selection
        sel_model = self._table_view.selectionModel()
        if sel_model is not None:
            sel_model.selectionChanged.connect(self._on_selection_changed)

        # Context menu
        self._table_view.customContextMenuRequested.connect(self._show_context_menu)

    def _initial_load(self) -> None:
        """Fetch scope and initial service list from backend."""

        def task() -> tuple[str, list[Service]]:
            scope_info = self.client.get_scope()
            services = self.client.list_services(scope=scope_info.active_scope)
            return scope_info.active_scope, services

        def on_success(result: tuple[str, list[Service]]) -> None:
            active_scope, services = result
            self._current_scope = active_scope
            self._toolbar.system_toggle.blockSignals(True)
            self._toolbar.system_toggle.setChecked(active_scope == "system")
            self._toolbar.system_toggle.blockSignals(False)
            self._populate_table(services)
            self.set_status(f"Connected to backend ({active_scope} scope)", success=True)

        def on_error(msg: str, exc: Any) -> None:
            self.set_status(f"Backend unavailable: {msg}", success=False)

        run_async_task(task, on_success=on_success, on_error=on_error)

    def request_service_list(self) -> None:
        """Fetch updated service list for the current scope."""
        if self._is_busy:
            return

        def task() -> list[Service]:
            return self.client.list_services(scope=self._current_scope)

        def on_start() -> None:
            self._is_busy = True
            self.set_status(f"Refreshing {self._current_scope} services...")

        def on_success(services: list[Service]) -> None:
            self._is_busy = False
            self._populate_table(services)
            self.set_status(f"Loaded {len(services)} services", success=True)

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            self.set_status(f"Failed to refresh services: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _populate_table(self, services: list[Service]) -> None:
        self._table_model.set_services(services)
        self._count_label.setText(f"{len(services)} services")
        self._detail_panel.clear()
        self._toolbar.set_actions_enabled(False)

    def _on_selection_changed(self, selected: QItemSelection, deselected: QItemSelection) -> None:
        indexes = self._table_view.selectionModel().selectedRows()
        if not indexes:
            self._toolbar.set_actions_enabled(False)
            self._detail_panel.clear()
            return

        self._toolbar.set_actions_enabled(True)
        source_index = self._filter_model.mapToSource(indexes[0])
        service = self._table_model.service_at(source_index.row())
        if service:
            self._detail_panel.show_service_details(service, scope=self._current_scope)

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
            f"Confirm {action}",
            f"Are you sure you want to <b>{action}</b> the service:<br><br><b>{service_name}</b>?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return reply == QMessageBox.StandardButton.Yes

    def _execute_service_op(self, op_name: str, fn: Any, *args: Any) -> None:
        name = self._selected_service_name()
        if not name or self._is_busy:
            return

        def task() -> ServiceOperationResult:
            return fn(name, scope=self._current_scope)

        def on_start() -> None:
            self._is_busy = True
            self._toolbar.set_actions_enabled(False)
            self.set_status(f"{op_name.capitalize()}ing '{name}'...")

        def on_success(res: ServiceOperationResult) -> None:
            self._is_busy = False
            msg = res.message or f"Service '{name}' {op_name}ed successfully."
            self.set_status(msg, success=True)
            self.request_service_list()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            self.set_status(f"Error {op_name}ing '{name}': {msg}", success=False)
            self._toolbar.set_actions_enabled(True)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

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

    def _on_reload_daemon_clicked(self) -> None:
        if self._is_busy:
            return

        def task() -> DaemonReloadResult:
            return self.client.reload_daemon(scope=self._current_scope)

        def on_start() -> None:
            self._is_busy = True
            self.set_status(f"Reloading systemd daemon ({self._current_scope} scope)...")

        def on_success(res: DaemonReloadResult) -> None:
            self._is_busy = False
            self.set_status(res.message or "Daemon reloaded successfully.", success=True)
            self.request_service_list()

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            self.set_status(f"Failed to reload daemon: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _on_create_clicked(self) -> None:
        dlg = CreateServiceDialog(self, client=self.client, default_scope=self._current_scope)
        if dlg.exec():
            self.request_service_list()

    def _on_system_scope_toggled(self, is_system: bool) -> None:
        new_scope = "system" if is_system else "user"
        if new_scope == self._current_scope:
            return
        self._detail_panel.clear()

        def task() -> tuple[str, list[Service]]:
            scope_info = self.client.set_scope(new_scope)
            services = self.client.list_services(scope=scope_info.active_scope)
            return scope_info.active_scope, services

        def on_start() -> None:
            self._is_busy = True
            self.set_status(f"Switching to {new_scope} scope...")

        def on_success(result: tuple[str, list[Service]]) -> None:
            self._is_busy = False
            active_scope, services = result
            self._current_scope = active_scope
            self._populate_table(services)
            self.set_status(
                f"Switched to {active_scope} scope ({len(services)} services)", success=True
            )

        def on_error(msg: str, exc: Any) -> None:
            self._is_busy = False
            # Revert checkbox state
            self._toolbar.system_toggle.blockSignals(True)
            self._toolbar.system_toggle.setChecked(self._current_scope == "system")
            self._toolbar.system_toggle.blockSignals(False)
            self.set_status(f"Failed to switch scope: {msg}", success=False)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)

    def _show_context_menu(self, pos: QPoint) -> None:
        index = self._table_view.indexAt(pos)
        if not index.isValid():
            return

        self._table_view.selectRow(index.row())

        is_dark = self._current_theme == "dark"
        neutral_color = QColor("#e5e9f0") if is_dark else QColor("#2d3748")
        success_color = QColor("#81C784") if is_dark else QColor("#2E7D32")
        danger_color = QColor("#E57373") if is_dark else QColor("#C62828")

        menu = QMenu(self)
        menu.setObjectName("contextMenu")

        menu.addAction(
            IconHelper.tinted_icon("media-playback-start", success_color),
            "Start",
            self._on_start_clicked,
        )
        menu.addAction(
            IconHelper.tinted_icon("media-playback-stop", danger_color),
            "Stop",
            self._on_stop_clicked,
        )
        menu.addAction(
            IconHelper.tinted_icon("view-refresh", neutral_color),
            "Restart",
            self._on_restart_clicked,
        )
        menu.addSeparator()
        menu.addAction(
            IconHelper.tinted_icon("emblem-default", success_color),
            "Enable",
            self._on_enable_clicked,
        )
        menu.addSeparator()
        menu.addAction(
            IconHelper.tinted_icon("action-mask", danger_color),
            "Mask",
            self._on_mask_clicked,
        )
        menu.addAction(
            IconHelper.tinted_icon("action-unmask", success_color),
            "Unmask",
            self._on_unmask_clicked,
        )

        global_pos = self._table_view.viewport().mapToGlobal(pos)
        menu.exec(global_pos)

    def set_status(self, message: str, success: bool | None = None) -> None:
        """Update status bar label and styling."""
        self._status_label.setText(message)
        if success is True:
            self._status_label.setStyleSheet("color: #4CAF50; font-weight: 500;")
        elif success is False:
            self._status_label.setStyleSheet("color: #F44336; font-weight: 500;")
        else:
            self._status_label.setStyleSheet("")

    def apply_theme(self, theme: str) -> None:
        """Apply dark or light theme stylesheet and refresh icons."""
        self._current_theme = theme
        qss_path = f":/styles/{theme}_theme.qss"
        file = QFile(qss_path)
        if file.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
            stylesheet = bytes(file.readAll()).decode("utf-8")
            self.setStyleSheet(stylesheet)
            file.close()

        self._toolbar.refresh_icons(is_dark=(theme == "dark"))

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
            "Manage, monitor, and configure services with ease.<br><br>"
            "Version 2.0.0<br>",
        )

    def keyPressEvent(self, event: Any) -> None:
        """Toggle menubar visibility when the Alt key is pressed, matching original ServiceDeck."""
        if event.key() == Qt.Key.Key_Alt:
            menubar = self.menuBar()
            if menubar is not None:
                menubar.setVisible(not menubar.isVisible())
        super().keyPressEvent(event)
