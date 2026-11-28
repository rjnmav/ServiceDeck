"""Dialog for authoring, editing, and installing systemd service unit files."""

import re
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import CreatedService
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette
from servicedeck.gui.views.dialogs.remote_onboarding import (
    LOCAL_TARGET,
    handle_elevation_error,
    needs_elevation,
)
from servicedeck.gui.views.unit_highlighter import UnitFileHighlighter
from servicedeck.gui.workers.service_worker import run_async_task

DEFAULT_SERVICE_TEMPLATE = (
    "[Unit]\n"
    "Description=My Custom Service\n"
    "After=network.target\n"
    "\n"
    "[Service]\n"
    "Type=simple\n"
    "ExecStart=/usr/bin/myapp\n"
    "Restart=on-failure\n"
    "RestartSec=5\n"
    "\n"
    "[Install]\n"
    "WantedBy=default.target\n"
)


class CreateServiceDialog(QDialog):
    """Streamlined modal dialog for creating a new systemd unit with live two-way sync."""

    def __init__(
        self,
        parent: Any = None,
        client: ServiceDeckClient | None = None,
        default_scope: str = "user",
        device_id: str | None = None,
        target: str | None = None,
        on_elevated: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create New Service")
        self.setMinimumSize(860, 580)
        self.setObjectName("createServiceDialog")
        self._client = client
        self._default_scope = default_scope
        self._device_id = device_id
        self._target = target or device_id or "this host"
        self._on_elevated = on_elevated
        self._theme = getattr(parent, "_current_theme", "dark")

        self._setup_ui()
        self._sync_editor_to_form()

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
        icon_lbl.setPixmap(IconHelper.svg_icon("terminal", palette.accent).pixmap(QSize(24, 24)))
        header_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)

        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title_label = QLabel("Create a New Systemd Service", header)
        title_label.setObjectName("contextTitle")

        subtitle_label = QLabel(
            "Configure the unit fields on the left or edit the systemd definition directly.",
            header,
        )
        subtitle_label.setObjectName("contextSubtitle")

        header_text.addWidget(title_label)
        header_text.addWidget(subtitle_label)
        header_layout.addLayout(header_text, 1)
        root.addWidget(header)

        # ─── Body ───
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 14)
        body_layout.setSpacing(12)

        split_layout = QHBoxLayout()
        split_layout.setSpacing(16)

        # ─── Left Pane (Scope + Properties Cards) ───
        left_pane_layout = QVBoxLayout()
        left_pane_layout.setSpacing(12)

        # Scope Card with Segmented Control
        scope_card = QFrame(body)
        scope_card.setObjectName("dialogCard")
        scope_card_layout = QVBoxLayout(scope_card)
        scope_card_layout.setContentsMargins(14, 12, 14, 12)
        scope_card_layout.setSpacing(8)

        scope_title = QLabel("Install Scope", scope_card)
        scope_title.setObjectName("propKey")
        scope_card_layout.addWidget(scope_title)

        scope_seg = QWidget(scope_card)
        scope_seg.setObjectName("scopeSegmented")
        scope_seg.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        seg_layout = QHBoxLayout(scope_seg)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(3)

        self._user_scope_btn = QPushButton("User Service", scope_seg)
        self._user_scope_btn.setObjectName("scopeBtn")
        self._user_scope_btn.setCheckable(True)
        self._user_scope_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        self._system_scope_btn = QPushButton("System Service", scope_seg)
        self._system_scope_btn.setObjectName("scopeBtn")
        self._system_scope_btn.setCheckable(True)
        self._system_scope_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        scope_group = QButtonGroup(scope_seg)
        scope_group.setExclusive(True)
        scope_group.addButton(self._user_scope_btn)
        scope_group.addButton(self._system_scope_btn)

        seg_layout.addWidget(self._user_scope_btn)
        seg_layout.addWidget(self._system_scope_btn)
        scope_card_layout.addWidget(scope_seg)

        # Hidden radio buttons kept synced for backward test/API compatibility
        self._user_radio = QRadioButton("User Service", scope_card)
        self._system_radio = QRadioButton("System Service", scope_card)
        self._user_radio.hide()
        self._system_radio.hide()

        if self._default_scope == "system":
            self._system_scope_btn.setChecked(True)
            self._system_radio.setChecked(True)
        else:
            self._user_scope_btn.setChecked(True)
            self._user_radio.setChecked(True)

        self._user_scope_btn.toggled.connect(self._user_radio.setChecked)
        self._system_scope_btn.toggled.connect(self._system_radio.setChecked)
        self._user_radio.toggled.connect(self._user_scope_btn.setChecked)
        self._system_radio.toggled.connect(self._system_scope_btn.setChecked)

        self._path_label = QLabel(scope_card)
        self._path_label.setWordWrap(True)
        self._path_label.setObjectName("contextSubtitle")
        scope_card_layout.addWidget(self._path_label)
        left_pane_layout.addWidget(scope_card)

        # Form Card
        form_card = QFrame(body)
        form_card.setObjectName("dialogCard")
        form_layout = QFormLayout(form_card)
        form_layout.setContentsMargins(14, 14, 14, 14)
        form_layout.setHorizontalSpacing(12)
        form_layout.setVerticalSpacing(12)
        form_layout.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        def lock_height(widget: QWidget) -> None:
            widget.setFixedHeight(36)
            widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

        self._name_edit = QLineEdit(form_card)
        self._name_edit.setPlaceholderText("my-service.service")
        self._name_edit.setObjectName("serviceNameEdit")
        lock_height(self._name_edit)
        form_layout.addRow("File Name:", self._name_edit)

        self._desc_edit = QLineEdit(form_card)
        self._desc_edit.setPlaceholderText("Description of the service")
        lock_height(self._desc_edit)
        form_layout.addRow("Description:", self._desc_edit)

        self._exec_edit = QLineEdit(form_card)
        self._exec_edit.setPlaceholderText("/usr/bin/my-command")
        lock_height(self._exec_edit)
        form_layout.addRow("ExecStart:", self._exec_edit)

        self._type_combo = QComboBox(form_card)
        self._type_combo.addItems(
            ["simple", "exec", "forking", "oneshot", "dbus", "notify", "idle"]
        )
        lock_height(self._type_combo)
        form_layout.addRow("Type:", self._type_combo)

        self._restart_combo = QComboBox(form_card)
        self._restart_combo.addItems(
            [
                "no",
                "always",
                "on-success",
                "on-failure",
                "on-abnormal",
                "on-abort",
                "on-watchdog",
            ]
        )
        self._restart_combo.setCurrentText("on-failure")
        lock_height(self._restart_combo)
        form_layout.addRow("Restart:", self._restart_combo)

        left_pane_layout.addWidget(form_card)
        left_pane_layout.addStretch()

        left_widget = QWidget(body)
        left_widget.setLayout(left_pane_layout)
        split_layout.addWidget(left_widget, 1)

        # ─── Right Pane (Unit Editor Card) ───
        editor_card = QFrame(body)
        editor_card.setObjectName("dialogCard")
        right_pane_layout = QVBoxLayout(editor_card)
        right_pane_layout.setContentsMargins(14, 12, 14, 14)
        right_pane_layout.setSpacing(8)

        content_label = QLabel("Unit File Preview & Editor", editor_card)
        content_label.setObjectName("propKey")
        right_pane_layout.addWidget(content_label)

        self._content_edit = QTextEdit(editor_card)
        self._content_edit.setObjectName("unitContentEdit")
        mono_font = QFont("Monospace", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self._content_edit.setFont(mono_font)
        self._content_edit.setPlainText(DEFAULT_SERVICE_TEMPLATE)
        self._content_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._highlighter = UnitFileHighlighter(self._content_edit.document(), self._theme)
        right_pane_layout.addWidget(self._content_edit, 1)

        split_layout.addWidget(editor_card, 1)
        body_layout.addLayout(split_layout, 1)

        # Reserved non-shifting validation/status banner
        self._banner_stack = QStackedWidget(body)
        self._banner_stack.setFixedHeight(42)
        self._banner_stack.addWidget(QWidget(self._banner_stack))

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
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel", footer)
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn = QPushButton("Create Service", footer)
        self._create_btn.setObjectName("primary")
        self._create_btn.setDefault(True)
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._create_btn)
        root.addWidget(footer)

        # ─── Connections ───
        self._cancel_btn.clicked.connect(self.reject)
        self._create_btn.clicked.connect(self._on_create)

        self._desc_edit.textChanged.connect(self._sync_form_to_editor)
        self._exec_edit.textChanged.connect(self._sync_form_to_editor)
        self._type_combo.currentTextChanged.connect(self._sync_form_to_editor)
        self._restart_combo.currentTextChanged.connect(self._sync_form_to_editor)

        self._content_edit.textChanged.connect(self._on_editor_changed)

        self._user_radio.toggled.connect(self._update_path_info)
        self._system_radio.toggled.connect(self._update_path_info)
        self._name_edit.textChanged.connect(self._on_name_changed)

        self._update_path_info()

    @property
    def _editor(self) -> QTextEdit:
        """Alias for _content_edit for backward compatibility with tests."""
        return self._content_edit

    def _set_name_invalid(self, invalid: bool) -> None:
        self._name_edit.setProperty("invalid", "true" if invalid else "false")
        self._name_edit.style().unpolish(self._name_edit)
        self._name_edit.style().polish(self._name_edit)

    def _show_banner(self, message: str, *, state: str = "error") -> None:
        self._status_banner.setText(message)
        self._status_banner.setProperty("state", state)
        self._status_banner.style().unpolish(self._status_banner)
        self._status_banner.style().polish(self._status_banner)
        self._banner_stack.setCurrentIndex(1)

    def _clear_banner(self) -> None:
        self._status_banner.setText("")
        self._banner_stack.setCurrentIndex(0)

    def _on_name_changed(self, text: str) -> None:
        if text.strip():
            self._set_name_invalid(False)
            self._clear_banner()
        self._update_path_info()

    def _on_editor_changed(self) -> None:
        if self._content_edit.toPlainText().strip():
            self._clear_banner()
        self._sync_editor_to_form()

    def _update_path_info(self) -> None:
        file_name = self._name_edit.text().strip()
        if not file_name:
            file_name = "my-service.service"
        elif not file_name.endswith(".service"):
            file_name += ".service"

        if self._user_radio.isChecked():
            self._path_label.setText(
                f"Target: <code>~/.config/systemd/user/{file_name}</code> (no root required)"
            )
        else:
            self._path_label.setText(
                f"Target: <code>/etc/systemd/system/{file_name}</code> (asks for the administrator password)"
            )

    def file_name(self) -> str:
        """Return the trimmed file name."""
        return self._name_edit.text().strip()

    def fileName(self) -> str:
        """C++ Qt naming alias for file_name."""
        return self.file_name()

    def content(self) -> str:
        """Return the raw unit file content."""
        return self._content_edit.toPlainText()

    def is_system_scope(self) -> bool:
        """Return True if system scope is selected."""
        return self._system_radio.isChecked()

    def isSystemScope(self) -> bool:
        """C++ Qt naming alias for is_system_scope."""
        return self.is_system_scope()

    def _extract_unit_key(self, section: str, key: str) -> str:
        content = self._content_edit.toPlainText()
        escaped_section = re.escape(f"[{section}]")
        section_re = re.compile(rf"{escaped_section}(.*?)(?:\n\[|$)", re.DOTALL)
        section_match = section_re.search(content)

        if section_match:
            section_content = section_match.group(1)
            key_re = re.compile(rf"^\s*{re.escape(key)}\s*=\s*(.*)$", re.MULTILINE)
            key_match = key_re.search(section_content)
            if key_match:
                return key_match.group(1).strip()
        return ""

    def _update_unit_key(self, section: str, key: str, value: str) -> None:
        content = self._content_edit.toPlainText()
        escaped_section = re.escape(f"[{section}]")
        section_re = re.compile(rf"({escaped_section}(?:\n.*?)?)(?:\n\[|$)", re.DOTALL)
        section_match = section_re.search(content)

        if section_match:
            section_content = section_match.group(1)
            key_re = re.compile(rf"^(\s*{re.escape(key)}\s*=).*$", re.MULTILINE)
            key_match = key_re.search(section_content)

            if not value and key_match:
                section_content = (
                    section_content[: key_match.start()]
                    + key_match.group(1)
                    + section_content[key_match.end() :]
                )
            elif key_match:
                section_content = (
                    section_content[: key_match.start()]
                    + key_match.group(1)
                    + value
                    + section_content[key_match.end() :]
                )
            elif value:
                if not section_content.endswith("\n"):
                    section_content += "\n"
                section_content += f"{key}={value}\n"

            new_content = (
                content[: section_match.start(1)]
                + section_content
                + content[section_match.end(1) :]
            )

            cursor_pos = self._content_edit.textCursor().position()
            self._content_edit.setPlainText(new_content)
            cursor = self._content_edit.textCursor()
            cursor.setPosition(min(cursor_pos, len(new_content)))
            self._content_edit.setTextCursor(cursor)
        elif value:
            if content and not content.endswith("\n\n") and not content.endswith("\n"):
                content += "\n"
            if content and not content.endswith("\n\n"):
                content += "\n"
            content += f"[{section}]\n{key}={value}\n"

            cursor_pos = self._content_edit.textCursor().position()
            self._content_edit.setPlainText(content)
            cursor = self._content_edit.textCursor()
            cursor.setPosition(min(cursor_pos, len(content)))
            self._content_edit.setTextCursor(cursor)

    def _sync_form_to_editor(self) -> None:
        self._content_edit.blockSignals(True)
        self._update_unit_key("Unit", "Description", self._desc_edit.text())
        self._update_unit_key("Service", "ExecStart", self._exec_edit.text())
        self._update_unit_key("Service", "Type", self._type_combo.currentText())
        self._update_unit_key("Service", "Restart", self._restart_combo.currentText())
        self._content_edit.blockSignals(False)

    def _sync_editor_to_form(self) -> None:
        self._desc_edit.blockSignals(True)
        self._exec_edit.blockSignals(True)
        self._type_combo.blockSignals(True)
        self._restart_combo.blockSignals(True)

        self._desc_edit.setText(self._extract_unit_key("Unit", "Description"))
        self._exec_edit.setText(self._extract_unit_key("Service", "ExecStart"))

        type_val = self._extract_unit_key("Service", "Type")
        if type_val:
            idx = self._type_combo.findText(type_val)
            if idx >= 0:
                self._type_combo.setCurrentIndex(idx)
            else:
                self._type_combo.setCurrentText(type_val)

        restart_val = self._extract_unit_key("Service", "Restart")
        if restart_val:
            idx = self._restart_combo.findText(restart_val)
            if idx >= 0:
                self._restart_combo.setCurrentIndex(idx)
            else:
                self._restart_combo.setCurrentText(restart_val)

        self._desc_edit.blockSignals(False)
        self._exec_edit.blockSignals(False)
        self._type_combo.blockSignals(False)
        self._restart_combo.blockSignals(False)

    def _on_create(self) -> None:
        raw_name = self._name_edit.text().strip()
        if not raw_name:
            self._set_name_invalid(True)
            self._show_banner("Please enter a service file name (e.g. my-service.service).")
            self._name_edit.setFocus()
            return

        name = raw_name if raw_name.endswith(".service") else f"{raw_name}.service"
        self._name_edit.setText(name)
        content_text = self.content().strip()
        if not content_text:
            self._show_banner("Service unit file content cannot be empty.")
            self._content_edit.setFocus()
            return

        scope = "system" if self.is_system_scope() else "user"

        if not self._client:
            self.accept()
            return

        self._submit(name, content_text, scope)

    def _submit(self, name: str, content_text: str, scope: str, *, _elevated: bool = False) -> None:
        """Create the unit; get administrator access once if a system unit needs it."""
        assert self._client is not None
        client = self._client
        device_id = self._device_id

        def task() -> CreatedService:
            return client.create_service(
                name=name, content=content_text, scope=scope, device_id=device_id
            )

        def on_start() -> None:
            self._create_btn.setEnabled(False)
            self._create_btn.setText("Creating...")
            self._show_banner(f"Creating '{name}' ({scope} scope)...", state="info")

        def on_success(res: CreatedService) -> None:
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create Service")
            QMessageBox.information(
                self,
                "Service Created",
                f"Service '{res.service}' successfully created at:\n\n{res.path}\n\n"
                "Systemd daemon configuration reloaded.",
            )
            self.accept()

        def show_failure(msg: str) -> None:
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create Service")
            self._show_banner(f"Failed to create '{name}': {msg}", state="error")
            QMessageBox.critical(
                self,
                "Creation Failed",
                f"Failed to create service '{name}':\n\n{msg}",
            )

        def on_error(msg: str, exc: Any) -> None:
            if not _elevated and needs_elevation(exc):
                self._create_btn.setText("Waiting for administrator access...")
                handle_elevation_error(
                    self,
                    client,
                    device_id,
                    exc,
                    target=self._target if device_id is not None else LOCAL_TARGET,
                    retry=lambda: self._submit(name, content_text, scope, _elevated=True),
                    on_give_up=show_failure,
                    on_elevated=self._on_elevated,
                )
                return
            show_failure(msg)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)
