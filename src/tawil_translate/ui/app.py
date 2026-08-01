from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .controller import DesktopController
from .global_hotkey import GlobalHotkey
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
    settings.api_check_requested.connect(controller.check_api)
    settings.model_download_requested.connect(controller.download_model)
    controller.running_changed.connect(settings.set_running)
    controller.status_changed.connect(settings.set_status)
    controller.api_models_ready.connect(settings.set_api_models)
    controller.api_check_failed.connect(settings.set_api_error)
    controller.model_download_finished.connect(settings.set_model_downloaded)
    controller.model_download_failed.connect(settings.set_model_error)
    hotkey = GlobalHotkey()
    app.installNativeEventFilter(hotkey)
    hotkey.activated.connect(lambda: overlay.set_edit_mode(not overlay.edit_mode))
    hotkey.register()
    settings.show()
    overlay.show()
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    app.aboutToQuit.connect(controller.stop)
    app.aboutToQuit.connect(hotkey.close)
    with loop:
        loop.run_forever()
    return 0
