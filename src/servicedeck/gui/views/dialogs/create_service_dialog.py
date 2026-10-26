"""Dialog for authoring, editing, and installing systemd service unit files matching original ServiceDeck."""

import re
from typing import Any

from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QTextEdit,
    QVBoxLayout,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import CreatedService
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
    """Dialog faithfully matching the original ServiceDeck C++ CreateServiceDialog."""

    def __init__(
        self,
        parent: Any = None,
        client: ServiceDeckClient | None = None,
        default_scope: str = "user",
        device_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Create New Service")
        self.setMinimumSize(850, 550)
        self.setObjectName("createServiceDialog")
        self._client = client
        self._default_scope = default_scope
        self._device_id = device_id

        self._setup_ui()

        # Initial sync from default template to form
        self._sync_editor_to_form()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(16)

        # ─── Header ───
        header_layout = QVBoxLayout()
        title_label = QLabel("Create a New Systemd Service", self)
        title_font = QFont()
        title_font.setPointSize(14)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setObjectName("dialogTitle")

        subtitle_label = QLabel(
            "Configure service properties below or edit the raw unit file directly.", self
        )
        subtitle_label.setObjectName("dialogSubtitle")
        subtitle_label.setStyleSheet("color: #718096;")

        header_layout.addWidget(title_label)
        header_layout.addWidget(subtitle_label)
        main_layout.addLayout(header_layout)

        # ─── Split Layout ───
        split_layout = QHBoxLayout()
        split_layout.setSpacing(20)

        # ─── Left Pane (Form) ───
        left_pane_layout = QVBoxLayout()

        # Scope selector
        scope_group = QGroupBox("Service Scope", self)
        scope_group.setObjectName("scopeGroup")
        scope_layout = QHBoxLayout(scope_group)

        self._user_radio = QRadioButton("User Service", scope_group)
        self._system_radio = QRadioButton("System Service", scope_group)
        self._user_radio.setToolTip("Installs to ~/.config/systemd/user/")
        self._system_radio.setToolTip("Installs to /etc/systemd/system/ (requires authentication)")

        if self._default_scope == "system":
            self._system_radio.setChecked(True)
        else:
            self._user_radio.setChecked(True)

        scope_layout.addWidget(self._user_radio)
        scope_layout.addWidget(self._system_radio)
        left_pane_layout.addWidget(scope_group)

        # Path preview label
        self._path_label = QLabel(self)
        self._path_label.setWordWrap(True)
        self._path_label.setStyleSheet("color: #a9b1d6; font-size: 11px; font-style: italic;")
        self._path_label.setObjectName("pathLabel")
        left_pane_layout.addWidget(self._path_label)

        # Form settings
        form_layout = QFormLayout()
        form_layout.setSpacing(12)

        self._name_edit = QLineEdit(self)
        self._name_edit.setPlaceholderText("my-service.service")
        self._name_edit.setObjectName("serviceNameEdit")
        form_layout.addRow("File Name:", self._name_edit)

        self._desc_edit = QLineEdit(self)
        self._desc_edit.setPlaceholderText("Description of the service")
        form_layout.addRow("Description:", self._desc_edit)

        self._exec_edit = QLineEdit(self)
        self._exec_edit.setPlaceholderText("/usr/bin/my-command")
        form_layout.addRow("ExecStart:", self._exec_edit)

        self._type_combo = QComboBox(self)
        self._type_combo.addItems(
            ["simple", "exec", "forking", "oneshot", "dbus", "notify", "idle"]
        )
        form_layout.addRow("Type:", self._type_combo)

        self._restart_combo = QComboBox(self)
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
        form_layout.addRow("Restart:", self._restart_combo)

        left_pane_layout.addLayout(form_layout)
        left_pane_layout.addStretch()

        split_layout.addLayout(left_pane_layout, 1)

        # ─── Right Pane (Editor) ───
        right_pane_layout = QVBoxLayout()
        content_label = QLabel("Unit File Preview & Editor:", self)
        bold_font = QFont(content_label.font())
        bold_font.setBold(True)
        content_label.setFont(bold_font)
        right_pane_layout.addWidget(content_label)

        self._content_edit = QTextEdit(self)
        self._content_edit.setObjectName("unitContentEdit")
        mono_font = QFont("Monospace", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)
        self._content_edit.setFont(mono_font)
        self._content_edit.setPlainText(DEFAULT_SERVICE_TEMPLATE)
        self._content_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        right_pane_layout.addWidget(self._content_edit, 1)

        split_layout.addLayout(right_pane_layout, 1)

        main_layout.addLayout(split_layout, 1)

        # ─── Buttons ───
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self._cancel_btn = QPushButton("Cancel", self)
        self._cancel_btn.setObjectName("cancelBtn")
        self._create_btn = QPushButton("Create", self)
        self._create_btn.setObjectName("primary")
        self._create_btn.setDefault(True)

        btn_layout.addWidget(self._cancel_btn)
        btn_layout.addWidget(self._create_btn)
        main_layout.addLayout(btn_layout)

        # ─── Connections ───
        self._cancel_btn.clicked.connect(self.reject)
        self._create_btn.clicked.connect(self._on_create)

        self._desc_edit.textChanged.connect(self._sync_form_to_editor)
        self._exec_edit.textChanged.connect(self._sync_form_to_editor)
        self._type_combo.currentTextChanged.connect(self._sync_form_to_editor)
        self._restart_combo.currentTextChanged.connect(self._sync_form_to_editor)

        self._content_edit.textChanged.connect(self._sync_editor_to_form)

        self._user_radio.toggled.connect(self._update_path_info)
        self._system_radio.toggled.connect(self._update_path_info)
        self._name_edit.textChanged.connect(self._update_path_info)

        self._update_path_info()

    @property
    def _editor(self) -> QTextEdit:
        """Alias for _content_edit for backward compatibility with tests."""
        return self._content_edit

    def _update_path_info(self) -> None:
        file_name = self._name_edit.text().strip()
        if not file_name:
            file_name = "my-service.service"
        elif not file_name.endswith(".service"):
            file_name += ".service"

        if self._user_radio.isChecked():
            self._path_label.setText(
                f"<b>User Mode:</b> Service will be installed to "
                f"<code>~/.config/systemd/user/{file_name}</code>. "
                f"This service runs under your user account and doesn't require root privileges."
            )
        else:
            self._path_label.setText(
                f"<b>System Mode:</b> Service will be installed to "
                f"<code>/etc/systemd/system/{file_name}</code>. "
                f"This service runs globally for all users and requires root (pkexec) to install."
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
            QMessageBox.warning(self, "Validation Error", "Please enter a service file name.")
            self._name_edit.setFocus()
            return

        name = raw_name if raw_name.endswith(".service") else f"{raw_name}.service"
        self._name_edit.setText(name)
        content_text = self.content().strip()
        if not content_text:
            QMessageBox.warning(
                self, "Validation Error", "Service unit file content cannot be empty."
            )
            return

        scope = "system" if self.is_system_scope() else "user"

        if not self._client:
            self.accept()
            return

        def task() -> CreatedService:
            return self._client.create_service(
                name=name, content=content_text, scope=scope, device_id=self._device_id
            )

        def on_start() -> None:
            self._create_btn.setEnabled(False)
            self._create_btn.setText("Creating...")

        def on_success(res: CreatedService) -> None:
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create")
            QMessageBox.information(
                self,
                "Service Created",
                f"Service '{res.service}' successfully created at:\n\n{res.path}\n\n"
                "Systemd daemon configuration reloaded.",
            )
            self.accept()

        def on_error(msg: str, exc: Any) -> None:
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create")
            QMessageBox.critical(
                self,
                "Creation Failed",
                f"Failed to create service '{name}':\n\n{msg}",
            )

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)
