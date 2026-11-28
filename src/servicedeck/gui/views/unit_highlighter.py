"""Syntax highlighting for systemd unit files: sections, keys, values and comments."""

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat, QTextDocument

from servicedeck.gui.resources.theme import get_palette

_SECTION = re.compile(r"^\s*\[[^\]]*\]\s*$")
_COMMENT = re.compile(r"^\s*[#;]")
_ASSIGNMENT = re.compile(r"^(\s*)([A-Za-z0-9_\-]+)(\s*=)")


class UnitFileHighlighter(QSyntaxHighlighter):
    """Colors a unit file using the active theme's tokens."""

    def __init__(self, document: QTextDocument, theme: str = "dark") -> None:
        super().__init__(document)
        self._formats: dict[str, QTextCharFormat] = {}
        self.set_theme(theme)

    def set_theme(self, theme: str) -> None:
        palette = get_palette(theme)

        def fmt(color: str, *, bold: bool = False, italic: bool = False) -> QTextCharFormat:
            char_format = QTextCharFormat()
            char_format.setForeground(QColor(color))
            if bold:
                char_format.setFontWeight(QFont.Weight.Bold)
            char_format.setFontItalic(italic)
            return char_format

        self._formats = {
            "section": fmt(palette.accent, bold=True),
            "key": fmt(palette.success_text),
            "equals": fmt(palette.text_muted),
            "comment": fmt(palette.text_muted, italic=True),
        }
        self.rehighlight()

    def highlightBlock(self, text: str) -> None:
        if _COMMENT.match(text):
            self.setFormat(0, len(text), self._formats["comment"])
            return
        if _SECTION.match(text):
            self.setFormat(0, len(text), self._formats["section"])
            return
        match = _ASSIGNMENT.match(text)
        if match:
            self.setFormat(match.start(2), len(match.group(2)), self._formats["key"])
            self.setFormat(match.end(2), len(match.group(3)), self._formats["equals"])


__all__ = ["UnitFileHighlighter"]
