"""Design tokens, QPalette builder, and theme loading helpers for ServiceDeck PySide6 GUI."""

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QFile
from PySide6.QtGui import QColor, QPalette

_RESOURCES_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class ThemePalette:
    """Semantic color palette shared between QSS stylesheets and custom delegates."""

    name: str
    is_dark: bool
    bg_app: str
    bg_sidebar: str
    bg_surface: str
    bg_elevated: str
    bg_hover: str
    bg_selected: str
    border: str
    text_primary: str
    text_secondary: str
    text_muted: str
    accent: str
    accent_hover: str
    on_accent: str
    success_text: str
    success_bg: str
    success_border: str
    danger_text: str
    danger_bg: str
    danger_border: str
    warning_text: str
    warning_bg: str
    warning_border: str
    muted_text: str
    muted_bg: str
    muted_border: str
    masked_text: str
    masked_bg: str
    masked_border: str

    def qcolor(self, value: str) -> QColor:
        """Convert a CSS hex or rgba() string into a QColor."""
        val = value.strip()
        if val.startswith("rgba(") and val.endswith(")"):
            parts = [p.strip() for p in val[5:-1].split(",")]
            if len(parts) == 4:
                r, g, b = int(parts[0]), int(parts[1]), int(parts[2])
                a_float = float(parts[3])
                a = round(a_float * 255) if a_float <= 1.0 else int(a_float)
                return QColor(r, g, b, a)
        return QColor(val)


DARK_PALETTE = ThemePalette(
    name="dark",
    is_dark=True,
    bg_app="#0F172A",
    bg_sidebar="#090E1A",
    bg_surface="#0F172A",
    bg_elevated="#1E293B",
    bg_hover="#1A2639",
    bg_selected="#1D3A5F",
    border="#263348",
    text_primary="#F8FAFC",
    text_secondary="#94A3B8",
    text_muted="#64748B",
    accent="#38BDF8",
    accent_hover="#0EA5E9",
    on_accent="#090E1A",
    success_text="#4ADE80",
    success_bg="rgba(34, 197, 94, 0.16)",
    success_border="rgba(34, 197, 94, 0.35)",
    danger_text="#F87171",
    danger_bg="rgba(239, 68, 68, 0.16)",
    danger_border="rgba(239, 68, 68, 0.35)",
    warning_text="#FBBF24",
    warning_bg="rgba(245, 158, 11, 0.16)",
    warning_border="rgba(245, 158, 11, 0.35)",
    muted_text="#94A3B8",
    muted_bg="rgba(148, 163, 184, 0.14)",
    muted_border="rgba(148, 163, 184, 0.25)",
    masked_text="#C084FC",
    masked_bg="rgba(168, 85, 247, 0.16)",
    masked_border="rgba(168, 85, 247, 0.35)",
)

LIGHT_PALETTE = ThemePalette(
    name="light",
    is_dark=False,
    bg_app="#FFFFFF",
    bg_sidebar="#F1F5F9",
    bg_surface="#FFFFFF",
    bg_elevated="#F8FAFC",
    bg_hover="#F1F5F9",
    bg_selected="#EFF6FF",
    border="#E2E8F0",
    text_primary="#0F172A",
    text_secondary="#475569",
    text_muted="#64748B",
    accent="#2563EB",
    accent_hover="#1D4ED8",
    on_accent="#FFFFFF",
    success_text="#15803D",
    success_bg="#DCFCE7",
    success_border="#BBF7D0",
    danger_text="#B91C1C",
    danger_bg="#FEE2E2",
    danger_border="#FECACA",
    warning_text="#B45309",
    warning_bg="#FEF3C7",
    warning_border="#FDE68A",
    muted_text="#475569",
    muted_bg="#F1F5F9",
    muted_border="#CBD5E1",
    masked_text="#7E22CE",
    masked_bg="#F3E8FF",
    masked_border="#E9D5FF",
)


def get_palette(theme: str) -> ThemePalette:
    """Return the ThemePalette for ``'dark'`` or ``'light'``."""
    return DARK_PALETTE if theme == "dark" else LIGHT_PALETTE


def build_qpalette(theme: str) -> QPalette:
    """Build a complete Qt QPalette so OS-native surfaces never bleed light gray into dark mode."""
    p = get_palette(theme)
    pal = QPalette()

    window = QColor(p.bg_app)
    base = QColor(p.bg_surface)
    alt_base = QColor(p.bg_elevated)
    text = QColor(p.text_primary)
    muted_text = QColor(p.text_muted)
    button = QColor(p.bg_elevated)
    border = QColor(p.border)
    accent = QColor(p.accent)
    on_accent = QColor(p.on_accent)

    for group in (
        QPalette.ColorGroup.Active,
        QPalette.ColorGroup.Inactive,
        QPalette.ColorGroup.Disabled,
    ):
        is_disabled = group == QPalette.ColorGroup.Disabled
        fg = muted_text if is_disabled else text

        pal.setColor(group, QPalette.ColorRole.Window, window)
        pal.setColor(group, QPalette.ColorRole.WindowText, fg)
        pal.setColor(group, QPalette.ColorRole.Base, base)
        pal.setColor(group, QPalette.ColorRole.AlternateBase, alt_base)
        pal.setColor(group, QPalette.ColorRole.ToolTipBase, alt_base)
        pal.setColor(group, QPalette.ColorRole.ToolTipText, text)
        pal.setColor(group, QPalette.ColorRole.Text, fg)
        pal.setColor(group, QPalette.ColorRole.Button, button)
        pal.setColor(group, QPalette.ColorRole.ButtonText, fg)
        pal.setColor(group, QPalette.ColorRole.BrightText, text)
        pal.setColor(group, QPalette.ColorRole.Highlight, accent)
        pal.setColor(group, QPalette.ColorRole.HighlightedText, on_accent)
        pal.setColor(group, QPalette.ColorRole.PlaceholderText, muted_text)
        pal.setColor(group, QPalette.ColorRole.Mid, border)
        pal.setColor(group, QPalette.ColorRole.Midlight, alt_base)
        pal.setColor(group, QPalette.ColorRole.Dark, QColor(p.bg_sidebar))
        pal.setColor(group, QPalette.ColorRole.Shadow, QColor(p.bg_sidebar))

    return pal


def load_stylesheet(theme: str) -> str:
    """Load the QSS stylesheet for ``theme`` from disk, falling back to Qt resources."""
    filename = "dark_theme.qss" if theme == "dark" else "light_theme.qss"
    disk_path = _RESOURCES_DIR / filename
    if disk_path.is_file():
        return disk_path.read_text(encoding="utf-8")

    qfile = QFile(f":/styles/{filename}")
    if qfile.open(QFile.OpenModeFlag.ReadOnly | QFile.OpenModeFlag.Text):
        data = bytes(qfile.readAll()).decode("utf-8")
        qfile.close()
        return data
    return ""
