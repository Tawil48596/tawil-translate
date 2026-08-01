from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tawil_translate.application.model_catalog import PROFILES
from tawil_translate.domain.config import AppConfig


class SettingsWindow(QMainWindow):
    mode_changed = Signal(bool)

    def __init__(self, config_path: Path, overlay) -> None:
        super().__init__()
        self.config_path = config_path
        self.config = AppConfig.load(config_path)
        self.overlay = overlay
        self.setWindowTitle("Tawil Translate")
        self.resize(620, 350)
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.addWidget(QLabel("实时游戏 / 直播翻译悬浮窗"))
        form = QFormLayout()
        self.profile = QComboBox()
        for item in PROFILES:
            vram = "CPU" if item.device == "cpu" else f"约 {item.approximate_vram_gb:.1f}GB 显存"
            self.profile.addItem(f"{item.label} · {item.model} · {vram}", item.id)
        index = self.profile.findData(self.config.stt.profile)
        self.profile.setCurrentIndex(max(0, index))
        form.addRow("本地语音识别", self.profile)
        self.profile_detail = QLabel()
        self.profile.currentIndexChanged.connect(self._update_detail)
        form.addRow("适用场景", self.profile_detail)
        self.opacity = QSlider()
        self.opacity.setOrientation(__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.Horizontal)
        self.opacity.setRange(30, 100)
        self.opacity.setValue(round(self.config.overlay.opacity * 100))
        self.opacity.valueChanged.connect(lambda value: self.overlay.setWindowOpacity(value / 100))
        form.addRow("悬浮窗透明度", self.opacity)
        self.click_through = QCheckBox("穿透鼠标点击（游戏模式）")
        self.click_through.setChecked(self.config.overlay.click_through)
        form.addRow("显示模式", self.click_through)
        layout.addLayout(form)
        buttons = QHBoxLayout()
        preview = QPushButton("显示悬浮窗")
        preview.clicked.connect(self.overlay.show)
        save = QPushButton("保存设置")
        save.clicked.connect(self._save)
        buttons.addWidget(preview)
        buttons.addStretch()
        buttons.addWidget(save)
        layout.addLayout(buttons)
        self.setCentralWidget(root)
        self._update_detail()

    def _update_detail(self) -> None:
        profile = PROFILES[self.profile.currentIndex()]
        self.profile_detail.setText(profile.use_case)

    def _save(self) -> None:
        self.config.stt.profile = self.profile.currentData()
        self.config.overlay.opacity = self.opacity.value() / 100
        self.config.overlay.click_through = self.click_through.isChecked()
        self.config.save(self.config_path)
        self.overlay.set_edit_mode(not self.config.overlay.click_through)
        self.statusBar().showMessage("设置已保存；模型将在下次启动时加载", 3500)
