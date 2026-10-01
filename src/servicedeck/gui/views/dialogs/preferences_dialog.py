"""Preferences dialog allowing customization of theme and refresh rates."""

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)


class PreferencesDialog(QDialog):
    """Dialog for editing user settings including light/dark theme."""

    theme_changed = Signal(str)
    preferences_changed = Signal(str, int, int)  # theme, log_interval, res_interval

    def __init__(
        self,
        current_theme: str = "dark",
        log_interval: int = 5,
        res_interval: int = 2,
        parent: Any = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preferences")
        self.setMinimumWidth(350)
        self._current_theme = current_theme
        self._log_interval = log_interval
        self._res_interval = res_interval
        self._setup_ui()

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        form_layout = QFormLayout()

        self._log_spin = QSpinBox(self)
        self._log_spin.setRange(1, 60)
        self._log_spin.setValue(self._log_interval)
        self._log_spin.setSuffix(" seconds")
        form_layout.addRow("Log Refresh Interval:", self._log_spin)

        self._res_spin = QSpinBox(self)
        self._res_spin.setRange(1, 60)
        self._res_spin.setValue(self._res_interval)
        self._res_spin.setSuffix(" seconds")
        form_layout.addRow("Resource Refresh Interval:", self._res_spin)

        self._theme_combo = QComboBox(self)
        self._theme_combo.addItems(["dark", "light"])
        idx = self._theme_combo.findText(self._current_theme)
        if idx >= 0:
            self._theme_combo.setCurrentIndex(idx)
        form_layout.addRow("UI Theme:", self._theme_combo)

        main_layout.addLayout(form_layout)
        main_layout.addStretch()

        btn_layout = QHBoxLayout()
        self._apply_btn = QPushButton("Apply", self)
        self._ok_btn = QPushButton("OK", self)
        self._cancel_btn = QPushButton("Cancel", self)
        self._ok_btn.setDefault(True)

        btn_layout.addStretch()
        btn_layout.addWidget(self._apply_btn)
        btn_layout.addWidget(self._ok_btn)
        btn_layout.addWidget(self._cancel_btn)

        main_layout.addLayout(btn_layout)

        self._apply_btn.clicked.connect(self._on_apply)
        self._ok_btn.clicked.connect(self._on_ok)
        self._cancel_btn.clicked.connect(self.reject)

    @property
    def selected_theme(self) -> str:
        return self._theme_combo.currentText()

    @property
    def log_interval(self) -> int:
        return self._log_spin.value()

    @property
    def resource_interval(self) -> int:
        return self._res_spin.value()

    def _on_apply(self) -> None:
        theme = self.selected_theme
        log_int = self.log_interval
        res_int = self.resource_interval
        self._current_theme = theme
        self._log_interval = log_int
        self._res_interval = res_int
        self.theme_changed.emit(theme)
        self.preferences_changed.emit(theme, log_int, res_int)

    def _on_ok(self) -> None:
        self._on_apply()
        self.accept()
