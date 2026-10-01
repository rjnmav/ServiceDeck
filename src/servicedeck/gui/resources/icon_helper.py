"""Utility for loading and dynamically tinting theme icons."""

from PySide6.QtGui import QColor, QIcon, QPainter


class IconHelper:
    """Helper to dynamically tint system theme icons according to active palette."""

    @staticmethod
    def tinted_icon(theme_name: str, color: QColor) -> QIcon:
        """Create a QIcon from a system theme icon tinted with the given QColor."""
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
