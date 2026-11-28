"""Dialog for editing a service through a drop-in override (``systemctl edit`` style)."""

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.service import OverrideResult, ServiceUnitFile
from servicedeck.backend.models.unit_syntax import check_unit_text
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import get_palette
from servicedeck.gui.views.dialogs.remote_onboarding import (
    LOCAL_TARGET,
    handle_elevation_error,
    needs_elevation,
)
from servicedeck.gui.views.unit_highlighter import UnitFileHighlighter
from servicedeck.gui.workers.service_worker import run_async_task

OVERRIDE_SKELETON = (
    "# Settings here are applied on top of the unit file.\n"
    "# To replace a list setting such as ExecStart=, reset it first with an empty\n"
    "# assignment (ExecStart=) and then add the new value.\n"
    "[Service]\n"
)

SAVE_LABEL = "Save && Reload"


class EditOverrideDialog(QDialog):
    """Edit ``<unit>.d/override.conf``; saving reloads systemd and rolls back on failure."""

    def __init__(
        self,
        parent: Any = None,
        client: ServiceDeckClient | None = None,
        unit: ServiceUnitFile | None = None,
        *,
        scope: str = "user",
        device_id: str | None = None,
        target: str | None = None,
        on_elevated: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        assert unit is not None
        self._client = client
        self._unit = unit
        self._scope = scope
        self._device_id = device_id
        self._target = target or device_id or LOCAL_TARGET
        self._on_elevated = on_elevated
        self._theme = getattr(parent, "_current_theme", "dark")
        self._result: OverrideResult | None = None
        self._initial = unit.override_content or OVERRIDE_SKELETON

        self.setWindowTitle(f"Edit {unit.service}")
        self.setObjectName("editOverrideDialog")
        self.setMinimumSize(900, 600)
        self._setup_ui()
        self._validate()

    @property
    def result_override(self) -> OverrideResult | None:
        """What the backend reported after a successful save."""
        return self._result

    @property
    def editor(self) -> QTextEdit:
        return self._override_edit

    def _setup_ui(self) -> None:
        palette = get_palette(self._theme)
        mono_font = QFont("Monospace", 10)
        mono_font.setStyleHint(QFont.StyleHint.Monospace)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ─── Header ───
        header = QWidget(self)
        header.setObjectName("dialogHeader")
        header.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(24, 16, 24, 16)
        header_layout.setSpacing(12)
        icon_lbl = QLabel(header)
        icon_lbl.setPixmap(IconHelper.svg_icon("edit", palette.accent).pixmap(QSize(24, 24)))
        header_layout.addWidget(icon_lbl, 0, Qt.AlignmentFlag.AlignTop)
        header_text = QVBoxLayout()
        header_text.setSpacing(2)
        title = QLabel(f"Edit {self._unit.service}", header)
        title.setObjectName("contextTitle")
        where = "on " + self._target if self._device_id is not None else "on this computer"
        subtitle = QLabel(
            f"Changes are written to <code>{self._unit.override_path}</code> {where} "
            f"({self._scope} scope). The vendor unit file is never modified.",
            header,
        )
        subtitle.setObjectName("contextSubtitle")
        subtitle.setWordWrap(True)
        header_text.addWidget(title)
        header_text.addWidget(subtitle)
        header_layout.addLayout(header_text, 1)
        root.addWidget(header)

        # ─── Body: current configuration | override editor ───
        body = QWidget(self)
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 18, 24, 14)
        body_layout.setSpacing(12)
        split = QHBoxLayout()
        split.setSpacing(14)

        current_card = QFrame(body)
        current_card.setObjectName("dialogCard")
        current_layout = QVBoxLayout(current_card)
        current_layout.setContentsMargins(14, 12, 14, 14)
        current_layout.setSpacing(8)
        current_label = QLabel("Current configuration (read-only)", current_card)
        current_label.setObjectName("propKey")
        current_layout.addWidget(current_label)
        self._current_view = QTextEdit(current_card)
        self._current_view.setObjectName("unitContentEdit")
        self._current_view.setReadOnly(True)
        self._current_view.setFont(mono_font)
        self._current_view.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._current_view.setPlainText(self._reference_text())
        self._current_highlighter = UnitFileHighlighter(self._current_view.document(), self._theme)
        current_layout.addWidget(self._current_view, 1)
        split.addWidget(current_card, 1)

        editor_card = QFrame(body)
        editor_card.setObjectName("dialogCard")
        editor_layout = QVBoxLayout(editor_card)
        editor_layout.setContentsMargins(14, 12, 14, 14)
        editor_layout.setSpacing(8)
        name = (self._unit.override_path or "override.conf").rsplit("/", 1)[-1]
        editor_label = QLabel(f"Override ({name})", editor_card)
        editor_label.setObjectName("propKey")
        editor_layout.addWidget(editor_label)
        self._override_edit = QTextEdit(editor_card)
        self._override_edit.setObjectName("unitContentEdit")
        self._override_edit.setAcceptRichText(False)
        self._override_edit.setFont(mono_font)
        self._override_edit.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self._override_edit.setPlainText(self._initial)
        self._override_highlighter = UnitFileHighlighter(
            self._override_edit.document(), self._theme
        )
        editor_layout.addWidget(self._override_edit, 1)
        split.addWidget(editor_card, 1)
        body_layout.addLayout(split, 1)

        # Reserved, non-shifting banner (same pattern as CreateServiceDialog).
        self._banner_stack = QStackedWidget(body)
        self._banner_stack.setFixedHeight(42)
        self._banner_stack.addWidget(QWidget(self._banner_stack))
        self._banner = QLabel("", self._banner_stack)
        self._banner.setObjectName("dialogBanner")
        self._banner.setWordWrap(True)
        self._banner.setAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
        self._banner_stack.addWidget(self._banner)
        body_layout.addWidget(self._banner_stack)
        root.addWidget(body, 1)

        # ─── Footer ───
        footer = QWidget(self)
        footer.setObjectName("dialogFooter")
        footer.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        footer_layout = QHBoxLayout(footer)
        footer_layout.setContentsMargins(24, 14, 24, 14)
        footer_layout.setSpacing(10)
        footer_layout.addStretch()
        self._cancel_btn = QPushButton("Cancel", footer)
        self._cancel_btn.setObjectName("cancelBtn")
        self._cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn = QPushButton(SAVE_LABEL, footer)
        self._save_btn.setObjectName("primary")
        self._save_btn.setDefault(True)
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        footer_layout.addWidget(self._cancel_btn)
        footer_layout.addWidget(self._save_btn)
        root.addWidget(footer)

        self._cancel_btn.clicked.connect(self.reject)
        self._save_btn.clicked.connect(self._on_save)
        self._override_edit.textChanged.connect(self._validate)

    def _reference_text(self) -> str:
        """The fragment plus every drop-in except the one being edited."""
        unit = self._unit
        parts = [f"# {unit.fragment_path or '(no unit file on disk)'}\n{unit.content.rstrip()}"]
        parts += [
            f"# {d.path}\n{d.content.rstrip()}"
            for d in unit.drop_ins
            if d.path != unit.override_path
        ]
        return "\n\n".join(parts) + "\n"

    # --- Validation and banner ---

    def _show_banner(self, message: str, *, state: str = "error") -> None:
        self._banner.setText(message)
        self._banner.setProperty("state", state)
        self._banner.style().unpolish(self._banner)
        self._banner.style().polish(self._banner)
        self._banner_stack.setCurrentIndex(1)

    def _clear_banner(self) -> None:
        self._banner.setText("")
        self._banner_stack.setCurrentIndex(0)

    def banner_text(self) -> str:
        return self._banner.text() if self._banner_stack.currentIndex() == 1 else ""

    def _validate(self) -> bool:
        report = check_unit_text(self._override_edit.toPlainText(), drop_in=True)
        self._save_btn.setEnabled(report.ok)
        if report.errors:
            self._show_banner(report.errors[0], state="error")
        elif report.empty:
            message = (
                "Only comments: saving removes the override."
                if self._unit.override_content is not None
                else "Add settings under a section such as [Service]."
            )
            self._show_banner(message, state="info")
        elif report.warnings:
            self._show_banner(report.warnings[0], state="info")
        else:
            self._clear_banner()
        return report.ok

    # --- Saving ---

    def _on_save(self) -> None:
        if not self._validate():
            return
        content = self._override_edit.toPlainText()
        if content == self._initial and self._unit.override_content is not None:
            self.reject()  # nothing changed
            return
        if self._client is None:
            self.accept()
            return
        self._submit(content)

    def _submit(self, content: str, *, _elevated: bool = False) -> None:
        assert self._client is not None
        client = self._client
        service, scope, device_id = self._unit.service, self._scope, self._device_id

        def task() -> OverrideResult:
            return client.write_override(service, content, scope=scope, device_id=device_id)

        def on_start() -> None:
            self._save_btn.setEnabled(False)
            self._override_edit.setReadOnly(True)
            self._save_btn.setText("Saving...")
            self._show_banner("Writing the override and reloading systemd...", state="info")

        def on_success(result: OverrideResult) -> None:
            self._result = result
            self.accept()

        def show_failure(msg: str) -> None:
            self._override_edit.setReadOnly(False)
            self._save_btn.setText(SAVE_LABEL)
            self._save_btn.setEnabled(True)
            self._show_banner(msg, state="error")

        def on_error(msg: str, exc: Any) -> None:
            if not _elevated and needs_elevation(exc):
                self._save_btn.setText("Waiting for administrator access...")
                handle_elevation_error(
                    self,
                    client,
                    device_id,
                    exc,
                    target=self._target if device_id is not None else LOCAL_TARGET,
                    retry=lambda: self._submit(content, _elevated=True),
                    on_give_up=show_failure,
                    on_elevated=self._on_elevated,
                )
                return
            show_failure(msg)

        run_async_task(task, on_start=on_start, on_success=on_success, on_error=on_error)


__all__ = ["OVERRIDE_SKELETON", "EditOverrideDialog"]
