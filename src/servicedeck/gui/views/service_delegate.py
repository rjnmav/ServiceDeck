"""Custom item delegate rendering 2-line service rows and pill badges."""

from typing import Any

from PySide6.QtCore import QModelIndex, QPersistentModelIndex, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate, QStyleOptionViewItem

from servicedeck.gui.models.service_model import ServiceTableModel
from servicedeck.gui.resources.icon_helper import IconHelper
from servicedeck.gui.resources.theme import DARK_PALETTE, ThemePalette, get_palette


class ServiceItemDelegate(QStyledItemDelegate):
    """Draws clean two-line Service cells and rounded status/startup pill badges."""

    ROW_HEIGHT = 54

    def __init__(self, parent: Any = None, theme: str = "dark") -> None:
        super().__init__(parent)
        self._palette: ThemePalette = get_palette(theme) if theme else DARK_PALETTE
        self._hovered_row: int = -1

    def set_hovered_row(self, row: int) -> None:
        """Track the currently hovered table row so all columns highlight uniformly."""
        self._hovered_row = row

    def set_theme(self, theme: str) -> None:
        """Update active color palette when theme switches."""
        self._palette = get_palette(theme)

    def sizeHint(
        self,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> QSize:
        hint = super().sizeHint(option, index)
        hint.setHeight(self.ROW_HEIGHT)
        return hint

    def paint(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = option.rect
        is_selected = bool(option.state & QStyle.StateFlag.State_Selected)
        is_hovered = index.row() == self._hovered_row or bool(
            option.state & QStyle.StateFlag.State_MouseOver
        )

        # Row background: selection > hover > live highlight > alternating
        bg_highlight = index.data(Qt.ItemDataRole.BackgroundRole)
        if is_selected:
            painter.fillRect(rect, QColor(self._palette.bg_selected))
        elif isinstance(bg_highlight, QColor):
            painter.fillRect(rect, bg_highlight)
        elif is_hovered:
            painter.fillRect(rect, QColor(self._palette.bg_hover))
        else:
            alt = index.row() % 2 == 1
            base = QColor(self._palette.bg_surface)
            if alt:
                base = base.lighter(106) if self._palette.is_dark else QColor("#FAFBFD")
            painter.fillRect(rect, base)

        # Left accent indicator on selected row (first column only)
        if is_selected and index.column() == ServiceTableModel.COL_SERVICE:
            painter.fillRect(
                QRect(rect.left(), rect.top() + 6, 3, rect.height() - 12),
                QColor(self._palette.accent),
            )

        # Subtle row bottom hairline
        painter.setPen(QPen(QColor(self._palette.border), 1))
        painter.drawLine(rect.left(), rect.bottom(), rect.right(), rect.bottom())

        col = index.column()
        if col == ServiceTableModel.COL_SERVICE:
            self._paint_service_cell(painter, option, index)
        elif col == ServiceTableModel.COL_STATUS:
            self._paint_status_pill(painter, option, index)
        elif col == ServiceTableModel.COL_STARTUP:
            self._paint_startup_pill(painter, option, index)

        painter.restore()

    def _paint_service_cell(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        rect = option.rect.adjusted(16, 8, -12, -8)
        name = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        desc = str(index.data(ServiceTableModel.ROLE_DESCRIPTION) or "")
        if index.data(ServiceTableModel.ROLE_WATCHED):
            # Watched for failures: a small bell at the right edge of the cell.
            bell_size = 14
            bell_rect = QRect(
                rect.right() - bell_size + 1,
                rect.top() + 2,
                bell_size,
                bell_size,
            )
            IconHelper.svg_icon("bell", self._palette.warning_text).paint(painter, bell_rect)
            rect = rect.adjusted(0, 0, -(bell_size + 6), 0)

        name_font = QFont(option.font)
        name_font.setWeight(QFont.Weight.DemiBold)
        name_font.setPointSize(max(9, option.font.pointSize()))

        desc_font = QFont(option.font)
        desc_font.setPointSize(max(8, option.font.pointSize() - 1))

        fm_name = QFontMetrics(name_font)
        fm_desc = QFontMetrics(desc_font)

        if desc:
            name_rect = QRect(rect.left(), rect.top(), rect.width(), fm_name.height() + 2)
            desc_rect = QRect(
                rect.left(),
                name_rect.bottom() + 2,
                rect.width(),
                fm_desc.height() + 2,
            )
            painter.setFont(name_font)
            painter.setPen(QColor(self._palette.text_primary))
            elided_name = fm_name.elidedText(name, Qt.TextElideMode.ElideRight, name_rect.width())
            painter.drawText(
                name_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided_name,
            )

            painter.setFont(desc_font)
            painter.setPen(QColor(self._palette.text_secondary))
            elided_desc = fm_desc.elidedText(desc, Qt.TextElideMode.ElideRight, desc_rect.width())
            painter.drawText(
                desc_rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided_desc,
            )
        else:
            painter.setFont(name_font)
            painter.setPen(QColor(self._palette.text_primary))
            elided_name = fm_name.elidedText(name, Qt.TextElideMode.ElideRight, rect.width())
            painter.drawText(
                rect,
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                elided_name,
            )

    def _status_colors(self, active_state: str) -> tuple[QColor, QColor, QColor]:
        p = self._palette
        if active_state == "active":
            return p.qcolor(p.success_text), p.qcolor(p.success_bg), p.qcolor(p.success_border)
        if active_state == "failed":
            return p.qcolor(p.danger_text), p.qcolor(p.danger_bg), p.qcolor(p.danger_border)
        if active_state == "inactive":
            return p.qcolor(p.muted_text), p.qcolor(p.muted_bg), p.qcolor(p.muted_border)
        return p.qcolor(p.warning_text), p.qcolor(p.warning_bg), p.qcolor(p.warning_border)

    def _startup_colors(self, startup_state: str) -> tuple[QColor, QColor, QColor]:
        p = self._palette
        if startup_state == "enabled":
            return p.qcolor(p.success_text), p.qcolor(p.success_bg), p.qcolor(p.success_border)
        if startup_state == "disabled":
            return p.qcolor(p.danger_text), p.qcolor(p.danger_bg), p.qcolor(p.danger_border)
        if startup_state == "masked":
            return p.qcolor(p.masked_text), p.qcolor(p.masked_bg), p.qcolor(p.masked_border)
        return p.qcolor(p.muted_text), p.qcolor(p.muted_bg), p.qcolor(p.muted_border)

    def _paint_pill(
        self,
        painter: QPainter,
        rect: QRect,
        text: str,
        fg: QColor,
        bg: QColor,
        border: QColor,
        font: QFont,
        *,
        draw_dot: bool = False,
    ) -> None:
        pill_font = QFont(font)
        pill_font.setWeight(QFont.Weight.DemiBold)
        pill_font.setPointSize(max(8, font.pointSize() - 1))
        fm = QFontMetrics(pill_font)

        dot_space = 12 if draw_dot else 0
        text_w = fm.horizontalAdvance(text)
        pill_w = min(rect.width() - 16, text_w + 26 + dot_space)
        pill_h = 24
        x = rect.left() + 12
        y = rect.center().y() - pill_h // 2
        pill_rect = QRectF(x, y, max(48, pill_w), pill_h)

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1))
        painter.drawRoundedRect(pill_rect, 12, 12)

        if draw_dot:
            painter.setBrush(fg)
            painter.setPen(Qt.PenStyle.NoPen)
            dot_x = pill_rect.left() + 10
            dot_y = pill_rect.center().y() - 3
            painter.drawEllipse(QRectF(dot_x, dot_y, 6, 6))

        text_rect = QRectF(
            pill_rect.left() + (18 if draw_dot else 6),
            pill_rect.top(),
            pill_rect.width() - (24 if draw_dot else 12),
            pill_rect.height(),
        )
        painter.setFont(pill_font)
        painter.setPen(fg)
        elided = fm.elidedText(text, Qt.TextElideMode.ElideRight, int(text_rect.width()) + 2)
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignCenter, elided)

    def _paint_status_pill(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        active_state = str(index.data(ServiceTableModel.ROLE_ACTIVE_STATE) or "")
        fg, bg, border = self._status_colors(active_state)
        self._paint_pill(painter, option.rect, text, fg, bg, border, option.font, draw_dot=True)

    def _paint_startup_pill(
        self,
        painter: QPainter,
        option: QStyleOptionViewItem,
        index: QModelIndex | QPersistentModelIndex,
    ) -> None:
        text = str(index.data(Qt.ItemDataRole.DisplayRole) or "")
        startup_state = str(index.data(ServiceTableModel.ROLE_UNIT_FILE_STATE) or "")
        fg, bg, border = self._startup_colors(startup_state)
        self._paint_pill(painter, option.rect, text, fg, bg, border, option.font, draw_dot=False)
