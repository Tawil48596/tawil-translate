from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tawil_translate.application.model_catalog import PROFILES, recommend_profile
from tawil_translate.domain.config import AppConfig
from tawil_translate.infrastructure.hardware import detect_cuda_vram_gb
from tawil_translate.infrastructure.processes import find_remembered_process, list_processes
from tawil_translate.infrastructure.secrets import set_api_key


class SettingsWindow(QMainWindow):
    mode_changed = Signal(bool)

    start_requested = Signal()
    stop_requested = Signal()

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
        self.model_progress = QProgressBar()
        self.model_progress.setRange(0, 0)
        self.model_progress.setFormat("正在检查、下载或预热本地模型…")
        self.model_progress.hide()
        layout.addWidget(self.model_progress)
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
        vram = detect_cuda_vram_gb()
        recommended = recommend_profile(vram, vram is not None)
        hardware = "未检测到 NVIDIA GPU" if vram is None else f"检测到约 {vram:.1f}GB 显存"
        self.recommendation = QLabel(f"{hardware}；推荐：{recommended.label}")
        apply_recommended = QPushButton("应用推荐")
        apply_recommended.clicked.connect(
            lambda: self.profile.setCurrentIndex(self.profile.findData(recommended.id))
        )
        recommendation_row = QHBoxLayout()
        recommendation_row.addWidget(self.recommendation, 1)
        recommendation_row.addWidget(apply_recommended)
        form.addRow("硬件建议", recommendation_row)
        self.api_base = QLineEdit(self.config.translation.base_url)
        form.addRow("翻译 API 地址", self.api_base)
        self.translation_model = QLineEdit(self.config.translation.model)
        form.addRow("翻译模型", self.translation_model)
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        self.api_key.setPlaceholderText("留空则沿用 Windows 凭据中已保存的密钥")
        form.addRow("API Key", self.api_key)
        process_row = QHBoxLayout()
        self.process = QComboBox()
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._refresh_processes)
        process_row.addWidget(self.process, 1)
        process_row.addWidget(refresh)
        form.addRow("目标游戏 / 直播", process_row)
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
        self.start_stop = QPushButton("开始翻译")
        self.start_stop.clicked.connect(self._toggle_running)
        buttons.addWidget(preview)
        buttons.addStretch()
        buttons.addWidget(save)
        buttons.addWidget(self.start_stop)
        layout.addLayout(buttons)
        self.setCentralWidget(root)
        self._update_detail()
        self._refresh_processes()
        self._running = False

    def _update_detail(self) -> None:
        profile = PROFILES[self.profile.currentIndex()]
        self.profile_detail.setText(profile.use_case)

    def _save(self) -> None:
        self.config.stt.profile = self.profile.currentData()
        self.config.overlay.opacity = self.opacity.value() / 100
        self.config.overlay.click_through = self.click_through.isChecked()
        self.config.translation.base_url = self.api_base.text().strip()
        self.config.translation.model = self.translation_model.text().strip()
        if self.api_key.text():
            set_api_key(self.config.translation.api_key_env, self.api_key.text())
            self.api_key.clear()
        selected = self.process.currentData()
        if selected:
            self.config.audio.target_pid = selected.pid
            self.config.audio.target_executable = selected.name
        self.config.save(self.config_path)
        self.overlay.set_edit_mode(not self.config.overlay.click_through)
        self.statusBar().showMessage("设置已保存；模型将在下次启动时加载", 3500)

    def _refresh_processes(self) -> None:
        self.process.clear()
        try:
            processes = list_processes()
        except (OSError, RuntimeError) as exc:
            self.statusBar().showMessage(f"无法读取进程：{exc}")
            return
        remembered = find_remembered_process(
            processes, self.config.audio.target_pid, self.config.audio.target_executable
        )
        selected_index = 0
        for index, process in enumerate(processes):
            self.process.addItem(process.label, process)
            if process.pid == remembered:
                selected_index = index
        self.process.setCurrentIndex(selected_index)

    def _toggle_running(self) -> None:
        if self._running:
            self.stop_requested.emit()
        else:
            self._save()
            self.start_requested.emit()

    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_stop.setText("停止翻译" if running else "开始翻译")
        self.profile.setEnabled(not running)
        self.process.setEnabled(not running)

    def set_status(self, state: str, detail: str) -> None:
        colors = {"listening": "#3ddc84", "working": "#4ba3ff", "error": "#ff5d62", "degraded": "#ffb020"}
        color = colors.get(state, "#89909f")
        self.statusBar().setStyleSheet(f"color: {color}")
        self.statusBar().showMessage(detail or state)
        downloading = state == "working" and "warming" in detail.casefold()
        self.model_progress.setVisible(downloading)
