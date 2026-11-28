"""Persistent GUI preferences store using XDG-compliant versioned JSON."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
DEFAULT_PREFERENCES_PATH: Path | None = None


def get_preferences_path() -> Path:
    """Return the XDG config file path for GUI preferences."""
    if DEFAULT_PREFERENCES_PATH is not None:
        return DEFAULT_PREFERENCES_PATH
    xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
    base = Path(xdg_config) if xdg_config else Path.home() / ".config"
    return base / "servicedeck" / "preferences.json"


class WatchedService(BaseModel):
    """A service whose failures raise a desktop notification. ``device_id`` None: local."""

    device_id: str | None = None
    scope: Literal["user", "system"] = "user"
    name: str


class GuiPreferences(BaseModel):
    """Schema-validated desktop GUI preferences and workspace layout state."""

    version: int = SCHEMA_VERSION
    theme: Literal["dark", "light"] = "dark"
    log_refresh_interval: int = Field(default=5, ge=1, le=60)
    resource_refresh_interval: int = Field(default=2, ge=1, le=60)
    window_maximized: bool = True
    window_geometry: str | None = None
    splitter_sizes: list[int] | None = None
    watched_services: list[WatchedService] = Field(default_factory=list)
    #: Show a desktop notification when a watched service fails.
    notify_on_failure: bool = True


class GuiPreferencesStore:
    """Loads and atomically persists ``GuiPreferences`` to XDG user config."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        """Resolved preferences file path."""
        return self._path if self._path is not None else get_preferences_path()

    def load(self) -> GuiPreferences:
        """Load saved preferences, falling back cleanly to defaults if missing or invalid."""
        target = self.path
        if not target.is_file():
            return GuiPreferences()

        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("Failed to read GUI preferences from %s: %s", target, exc)
            return GuiPreferences()

        if not isinstance(raw, dict):
            logger.warning("Ignoring non-object GUI preferences in %s", target)
            return GuiPreferences()

        try:
            return GuiPreferences.model_validate(raw)
        except ValidationError:
            # Recover valid fields individually rather than discarding everything on one bad key.
            defaults = GuiPreferences().model_dump()
            recovered: dict[str, object] = {}
            for key, default_val in defaults.items():
                if key not in raw:
                    recovered[key] = default_val
                    continue
                candidate = {**defaults, key: raw[key]}
                try:
                    validated = GuiPreferences.model_validate(candidate)
                    recovered[key] = getattr(validated, key)
                except ValidationError:
                    logger.warning(
                        "Invalid GUI preference '%s' in %s; falling back to default", key, target
                    )
                    recovered[key] = default_val
            return GuiPreferences.model_validate(recovered)

    def save(self, prefs: GuiPreferences) -> None:
        """Persist preferences atomically using a temporary file and rename."""
        target = self.path
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_file = target.with_name(f".{target.name}.{os.getpid()}.tmp")

        payload = prefs.model_dump(mode="json")
        try:
            with open(temp_file, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
                fh.write("\n")
                fh.flush()
                os.fsync(fh.fileno())
            temp_file.replace(target)
        except Exception as exc:
            temp_file.unlink(missing_ok=True)
            logger.error("Failed to save GUI preferences to %s: %s", target, exc)
            raise
