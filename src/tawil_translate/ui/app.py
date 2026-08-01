from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .controller import DesktopController
from .overlay import SubtitleOverlay
from .settings import SettingsWindow


def run_desktop(config_path: Path) -> int:
    from qasync import QEventLoop

    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName("Tawil Translate")
    overlay = SubtitleOverlay()
    settings = SettingsWindow(config_path, overlay)
    controller = DesktopController(config_path, overlay)
    settings.start_requested.connect(controller.start)
    settings.stop_requested.connect(controller.stop)
    controller.running_changed.connect(settings.set_running)
    controller.status_changed.connect(settings.set_status)
    settings.show()
    overlay.show()
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(controller.stop)
    with loop:
        loop.run_forever()
    return 0
