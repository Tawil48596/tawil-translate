from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen, QTextLayout
from PySide6.QtWidgets import QWidget


@dataclass(slots=True)
class _CaptionRow:
    utterance_id: str
    source: str
    translated: str = ""


class SubtitleOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[_CaptionRow] = []
        self.preview_text = "Source subtitle preview"
        self.preview_translation = ""
        self.max_rows = 4
        self.edit_mode = True
        self.health_state = "idle"
        self._scroll_offset = 0.0
        self.setWindowTitle("Tawil Translate Overlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(900, 320)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(50)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._scroll = QPropertyAnimation(self, b"scrollOffset", self)
        self._scroll.setDuration(220)
        self._scroll.setEasingCurve(QEasingCurve.OutCubic)

    def set_subtitle(
        self,
        utterance_id: str,
        source: str,
        translated: str,
        is_final: bool = False,
    ) -> None:
        if utterance_id == "preview":
            self.preview_text = source
            self.preview_translation = translated
            self.update()
            return

        self.preview_text = ""
        self.preview_translation = ""
        row = next((item for item in self.rows if item.utterance_id == utterance_id), None)
        if row is None:
            row = _CaptionRow(utterance_id, source, translated)
            self.rows.append(row)
            if len(self.rows) > self.max_rows:
                self.rows.pop(0)
            self._animate_scroll(96 if translated else 62)
        else:
            row.source = source
            if translated or is_final:
                row.translated = translated
            self.update()
        self._animate_fade()

    def _animate_scroll(self, distance: float) -> None:
        self._scroll.stop()
        self._scroll.setStartValue(distance)
        self._scroll.setEndValue(0.0)
        self._scroll.start()

    def _animate_fade(self) -> None:
        self._fade.stop()
        self.setWindowOpacity(0.82)
        self._fade.setStartValue(0.82)
        self._fade.setEndValue(1.0)
        self._fade.start()

    def _get_scroll_offset(self) -> float:
        return self._scroll_offset

    def _set_scroll_offset(self, value: float) -> None:
        self._scroll_offset = value
        self.update()

    scrollOffset = Property(float, _get_scroll_offset, _set_scroll_offset)

    def set_health(self, state: str) -> None:
        self.health_state = state
        self.update()

    def set_edit_mode(self, enabled: bool) -> None:
        self.edit_mode = enabled
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not enabled)
        self.setWindowFlag(Qt.WindowTransparentForInput, not enabled)
        self.show()
        self.update()

    def mousePressEvent(self, event) -> None:
        if self.edit_mode and event.button() == Qt.LeftButton:
            self.windowHandle().startSystemMove()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        if self.edit_mode:
            painter.setBrush(QColor(10, 12, 18, 150))
            painter.setPen(QColor(100, 170, 255, 120))
            painter.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 16, 16)
        colors = {
            "listening": "#3ddc84",
            "working": "#4ba3ff",
            "error": "#ff5d62",
            "degraded": "#ffb020",
        }
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(colors.get(self.health_state, "#89909f")))
        painter.drawEllipse(self.width() - 20, 10, 8, 8)

        items: list[tuple[str, str, bool]] = [
            (row.source, row.translated, False) for row in self.rows
        ]
        if self.preview_text:
            items.append((self.preview_text, self.preview_translation, True))
        heights = [96 if translated else 58 for _, translated, _ in items]
        content_height = sum(heights) + max(0, len(items) - 1) * 8
        y = max(20.0, self.height() - content_height - 18.0) + self._scroll_offset
        for index, ((source, translated, preview), height) in enumerate(zip(items, heights)):
            painter.setOpacity(0.55 + 0.45 * (index + 1) / max(1, len(items)))
            if translated:
                self._draw_outlined(
                    painter, source, QRectF(25, y, self.width() - 50, 32), QColor(165, 180, 202), 16
                )
                self._draw_outlined(
                    painter,
                    translated,
                    QRectF(25, y + 34, self.width() - 50, 58),
                    QColor(255, 255, 255),
                    23,
                )
            else:
                color = QColor(145, 178, 220) if preview else QColor(255, 255, 255)
                self._draw_outlined(
                    painter, source, QRectF(25, y, self.width() - 50, 54), color, 22
                )
            y += height + 8
        painter.setOpacity(1.0)

    def _draw_outlined(self, painter, text, rect, color, size) -> None:
        font = QFont("Microsoft YaHei UI", size, QFont.DemiBold)
        layout = QTextLayout(text, font)
        path = QPainterPath()
        layout.beginLayout()
        y = rect.y()
        while True:
            line = layout.createLine()
            if not line.isValid() or y >= rect.bottom():
                break
            line.setLineWidth(rect.width())
            content = text[line.textStart() : line.textStart() + line.textLength()]
            path.addText(rect.x(), y + line.ascent(), font, content)
            y += line.height()
        layout.endLayout()
        painter.setBrush(color)
        painter.setPen(Qt.NoPen)
        painter.drawPath(path)
        painter.strokePath(path, QPen(QColor(0, 0, 0, 230), 3))
