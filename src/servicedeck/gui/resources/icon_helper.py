"""Vector SVG icon registry and dynamic theme-tinting helper."""

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# Clean 24x24 Lucide-style stroke SVG paths. Using `currentColor` allows exact tinting.
_SVG_PATHS: dict[str, str] = {
    "server": (
        '<rect x="2" y="2" width="20" height="8" rx="2" ry="2"/>'
        '<rect x="2" y="14" width="20" height="8" rx="2" ry="2"/>'
        '<line x1="6" y1="6" x2="6.01" y2="6"/>'
        '<line x1="6" y1="18" x2="6.01" y2="18"/>'
    ),
    "monitor": (
        '<rect x="2" y="3" width="20" height="14" rx="2" ry="2"/>'
        '<line x1="8" y1="21" x2="16" y2="21"/>'
        '<line x1="12" y1="17" x2="12" y2="21"/>'
    ),
    "plus": ('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>'),
    "refresh": (
        '<path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/>'
        '<path d="M3 3v5h5"/>'
        '<path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/>'
        '<path d="M16 16h5v5"/>'
    ),
    "play": '<polygon points="6 3 20 12 6 21 6 3"/>',
    "stop": '<rect x="5" y="5" width="14" height="14" rx="2"/>',
    "restart": ('<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'),
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "ban": ('<circle cx="12" cy="12" r="10"/><line x1="4.93" y1="4.93" x2="19.07" y2="19.07"/>'),
    "lock": (
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 10 0v4"/>'
    ),
    "unlock": (
        '<rect x="3" y="11" width="18" height="11" rx="2" ry="2"/>'
        '<path d="M7 11V7a5 5 0 0 1 9.9-1"/>'
    ),
    "shield": '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
    "settings": (
        '<circle cx="12" cy="12" r="3"/>'
        '<path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06'
        "a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09"
        "a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83"
        "l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09"
        "a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83"
        "l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09"
        "a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83"
        "l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09"
        'a1.65 1.65 0 0 0-1.51 1z"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 2v2"/><path d="M12 20v2"/>'
        '<path d="m4.93 4.93 1.41 1.41"/><path d="m17.66 17.66 1.41 1.41"/>'
        '<path d="M2 12h2"/><path d="M20 12h2"/>'
        '<path d="m6.34 17.66-1.41 1.41"/><path d="m19.07 4.93-1.41 1.41"/>'
    ),
    "moon": '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
    "search": ('<circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/>'),
    "close": ('<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>'),
    "more": (
        '<circle cx="12" cy="12" r="1.5" fill="currentColor" stroke="none"/>'
        '<circle cx="19" cy="12" r="1.5" fill="currentColor" stroke="none"/>'
        '<circle cx="5" cy="12" r="1.5" fill="currentColor" stroke="none"/>'
    ),
    "copy": (
        '<rect x="9" y="9" width="13" height="13" rx="2" ry="2"/>'
        '<path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>'
    ),
    "chevron-down": '<polyline points="6 9 12 15 18 9"/>',
    "chevron-right": '<polyline points="9 18 15 12 9 6"/>',
    "terminal": ('<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>'),
    "edit": ('<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/>'),
    "bell": (
        '<path d="M6 8a6 6 0 0 1 12 0c0 7 3 9 3 9H3s3-2 3-9"/>'
        '<path d="M10.3 21a1.94 1.94 0 0 0 3.4 0"/>'
    ),
    "undo": ('<path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-15-6.7L3 13"/>'),
}

# Map legacy freedesktop theme names to our bundled SVG names so existing callers stay crisp.
_LEGACY_ALIASES: dict[str, str] = {
    "media-playback-start": "play",
    "media-playback-stop": "stop",
    "view-refresh": "refresh",
    "emblem-default": "check",
    "process-stop": "ban",
    "system-reboot": "restart",
    "list-add": "plus",
    "action-mask": "lock",
    "action-unmask": "unlock",
}


class IconHelper:
    """Helper to render crisp bundled vector SVG icons or tinted system theme icons."""

    @staticmethod
    def svg_icon(name: str, color: QColor | str) -> QIcon:
        """Render a bundled SVG icon by ``name`` tinted with ``color``."""
        key = _LEGACY_ALIASES.get(name, name)
        paths = _SVG_PATHS.get(key)
        if not paths:
            return QIcon()

        color_hex = color.name() if isinstance(color, QColor) else color
        svg = (
            '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
            'viewBox="0 0 24 24" fill="none" stroke="currentColor" '
            'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
            f"{paths}</svg>"
        ).replace("currentColor", color_hex)

        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        icon = QIcon()
        for size in (16, 20, 24, 32):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            renderer.render(painter, QRectF(0, 0, size, size))
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    @staticmethod
    def tinted_icon(theme_name: str, color: QColor) -> QIcon:
        """Return a bundled vector icon if available, otherwise tint a system theme icon."""
        if theme_name in _SVG_PATHS or theme_name in _LEGACY_ALIASES:
            return IconHelper.svg_icon(theme_name, color)

        base_icon = QIcon.fromTheme(theme_name)
        if base_icon.isNull():
            return QIcon()

        tinted = QIcon()
        for size in (16, 20, 24, 32, 48):
            pixmap = base_icon.pixmap(size, size)
            if pixmap.isNull():
                continue

            painter = QPainter(pixmap)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pixmap.rect(), color)
            painter.end()

            tinted.addPixmap(pixmap)

        return tinted
