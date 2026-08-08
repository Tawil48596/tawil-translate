import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from tawil_translate.ui.overlay import SubtitleOverlay


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_translation_updates_matching_recognition_row() -> None:
    _app()
    overlay = SubtitleOverlay()

    overlay.set_subtitle("line-1", "Hello world", "", False)
    overlay.set_subtitle("line-1", "Hello world", "你好，世界", True)

    assert len(overlay.rows) == 1
    assert overlay.rows[0].source == "Hello world"
    assert overlay.rows[0].translated == "你好，世界"


def test_preview_does_not_enter_scrolling_history() -> None:
    _app()
    overlay = SubtitleOverlay()

    overlay.set_subtitle("preview", "Hello wor", "", False)
    assert overlay.rows == []
    assert overlay.preview_text == "Hello wor"

    overlay.set_subtitle("preview", "Hello world", "你好，世界", False)
    assert overlay.preview_translation == "你好，世界"

    overlay.set_subtitle("line-1", "Hello world", "", False)
    assert [row.utterance_id for row in overlay.rows] == ["line-1"]
    assert overlay.preview_text == ""
    assert overlay.preview_translation == ""


def test_history_keeps_latest_four_rows() -> None:
    _app()
    overlay = SubtitleOverlay()

    for index in range(6):
        overlay.set_subtitle(str(index), f"source {index}", "", False)

    assert [row.utterance_id for row in overlay.rows] == ["2", "3", "4", "5"]
