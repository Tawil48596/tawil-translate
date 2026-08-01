from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QPropertyAnimation, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath
from PySide6.QtWidgets import QWidget


class SubtitleOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.source_text = "Source subtitle preview"
        self.translated_text = "翻译字幕预览"
        self.edit_mode = True
        self.setWindowTitle("Tawil Translate Overlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.resize(900, 180)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(50)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)

    def set_subtitle(self, source: str, translated: str) -> None:
        self.source_text, self.translated_text = source, translated
        self._fade.stop()
        self.setWindowOpacity(0.72)
        self._fade.setStartValue(0.72)
        self._fade.setEndValue(1.0)
        self._fade.start()
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
        self._draw_outlined(painter, self.source_text, 25, 18, QColor(205, 210, 220), 18)
        self._draw_outlined(painter, self.translated_text, 25, 72, QColor(255, 255, 255), 28)

    def _draw_outlined(self, painter, text, x, y, color, size) -> None:
        font = QFont("Microsoft YaHei UI", size, QFont.DemiBold)
        path = QPainterPath()
        path.addText(x, y + size, font, text)
        painter.setPen(QColor(0, 0, 0, 230))
        painter.setBrush(color)
        painter.drawPath(path)
        painter.strokePath(path, painter.pen())
