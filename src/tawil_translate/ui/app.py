from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .overlay import SubtitleOverlay
from .settings import SettingsWindow


def run_desktop(config_path: Path) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Tawil Translate")
    overlay = SubtitleOverlay()
    settings = SettingsWindow(config_path, overlay)
    settings.show()
    overlay.show()
    return app.exec()
