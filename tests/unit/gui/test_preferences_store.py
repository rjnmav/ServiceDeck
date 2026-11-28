"""Unit tests for persistent GUI preferences and MainWindow restoration."""

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QThreadPool

from servicedeck.api_client import ServiceDeckClient
from servicedeck.api_client.models.common import ScopeInfo
from servicedeck.gui import preferences
from servicedeck.gui.preferences import GuiPreferences, GuiPreferencesStore, get_preferences_path
from servicedeck.gui.views.main_window import MainWindow


def test_get_preferences_path_respects_xdg_config_home(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preferences, "DEFAULT_PREFERENCES_PATH", None)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "custom-xdg"))
    assert get_preferences_path() == tmp_path / "custom-xdg" / "servicedeck" / "preferences.json"


def test_preferences_store_roundtrip_and_atomic_write(tmp_path: Path) -> None:
    store = GuiPreferencesStore(tmp_path / "prefs" / "preferences.json")
    assert store.load() == GuiPreferences()

    saved = GuiPreferences(
        theme="light",
        log_refresh_interval=12,
        resource_refresh_interval=4,
        window_maximized=False,
        splitter_sizes=[700, 420],
    )
    store.save(saved)

    assert store.path.is_file()
    assert list(store.path.parent.glob("*.tmp")) == []
    assert store.load() == saved


def test_preferences_store_recovers_from_invalid_or_corrupt_data(tmp_path: Path) -> None:
    path = tmp_path / "preferences.json"
    store = GuiPreferencesStore(path)

    # Corrupt JSON falls back cleanly to defaults
    path.write_text("{not valid json", encoding="utf-8")
    assert store.load() == GuiPreferences()

    # One invalid field preserves valid fields from the same file
    path.write_text(
        '{"theme": "neon", "log_refresh_interval": 15, "resource_refresh_interval": 999}',
        encoding="utf-8",
    )
    loaded = store.load()
    assert loaded.theme == "dark"
    assert loaded.log_refresh_interval == 15
    assert loaded.resource_refresh_interval == 2


def test_main_window_persists_and_restores_theme_and_intervals(qapp: Any, tmp_path: Path) -> None:
    store = GuiPreferencesStore(tmp_path / "preferences.json")
    client = MagicMock(spec=ServiceDeckClient)
    client.get_scope.return_value = ScopeInfo(active_scope="user", available_scopes=["user"])
    client.list_devices.return_value = []
    client.list_services.return_value = []

    win1 = MainWindow(client=client, preferences_store=store)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()
    assert win1._current_theme == "dark"

    # Toggle to light via sidebar action and update intervals via preferences handler
    win1._on_toggle_theme()
    assert win1._current_theme == "light"
    assert store.load().theme == "light"

    win1._on_preferences_updated("light", 11, 6)
    win1.close()
    QThreadPool.globalInstance().waitForDone(2000)

    # Reopen a brand new MainWindow with the same store -> restores light theme & intervals
    win2 = MainWindow(client=client, preferences_store=store)
    QThreadPool.globalInstance().waitForDone(2000)
    qapp.processEvents()
    assert win2._current_theme == "light"
    assert win2._log_refresh_interval == 11
    assert win2._resource_refresh_interval == 6
    assert win2._detail_panel._log_timer.interval() == 11000
    assert win2._detail_panel._resource_timer.interval() == 6000
    win2.close()
    QThreadPool.globalInstance().waitForDone(2000)
