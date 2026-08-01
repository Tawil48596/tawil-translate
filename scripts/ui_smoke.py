from __future__ import annotations

import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QWidget

from tawil_translate.ui.settings import SettingsWindow


class FakeOverlay(QWidget):
    def set_edit_mode(self, enabled: bool) -> None:
        self.setEnabled(enabled)


def main() -> None:
    app = QApplication([])
    with tempfile.TemporaryDirectory() as directory:
        window = SettingsWindow(Path(directory) / "user_config.json", FakeOverlay())
        window.show()
        app.processEvents()
        assert window.check_api_button.text() == "保存并检查连接"
        assert not window.start_stop.isEnabled()
        window.close()


if __name__ == "__main__":
    main()
