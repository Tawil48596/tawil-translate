from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from tawil_translate.application.model_catalog import PROFILES, recommend_profile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.domain.config import AppConfig
from tawil_translate.infrastructure.hardware import detect_cuda_vram_gb
from tawil_translate.infrastructure.processes import find_remembered_process, list_processes
from tawil_translate.infrastructure.secrets import get_api_key, set_api_key
from tawil_translate.paths import model_root

STYLE = """
QWidget { background: #090d14; color: #d9e2f1; font-family: "Microsoft YaHei UI"; font-size: 13px; }
QMainWindow { background: #090d14; }
QFrame#card { background: #101722; border: 1px solid #1d2a3a; border-radius: 12px; }
QLabel#title { color: #f3f7ff; font-size: 24px; font-weight: 700; }
QLabel#subtitle { color: #74849a; font-size: 12px; }
QLabel#section { color: #edf4ff; font-size: 15px; font-weight: 650; }
QLabel#hint { color: #8292a8; font-size: 12px; }
QLabel#success { color: #48d597; }
QLabel#error { color: #ff6978; }
QLineEdit, QComboBox { background: #0b111a; border: 1px solid #26364a; border-radius: 8px; padding: 9px 11px; min-height: 20px; }
QLineEdit:focus, QComboBox:focus { border: 1px solid #45a3ff; }
QComboBox::drop-down { border: 0; width: 28px; }
QPushButton { background: #172334; border: 1px solid #29405a; border-radius: 8px; padding: 9px 15px; color: #dce8f8; }
QPushButton:hover { background: #20334b; border-color: #3e6d98; }
QPushButton:disabled { color: #526075; background: #111822; border-color: #1c2735; }
QPushButton#primary { background: #1976d2; border-color: #2f92ee; color: white; font-weight: 650; }
QPushButton#primary:hover { background: #2388ed; }
QProgressBar { background: #091019; border: 1px solid #203148; border-radius: 5px; height: 8px; text-align: center; color: transparent; }
QProgressBar::chunk { background: #38a4ff; border-radius: 4px; }
QSlider::groove:horizontal { background: #253246; height: 4px; border-radius: 2px; }
QSlider::handle:horizontal { background: #53b0ff; width: 14px; margin: -5px 0; border-radius: 7px; }
QStatusBar { background: #0b1119; border-top: 1px solid #182334; color: #8292a8; }
QScrollArea { border: 0; }
"""


class SettingsWindow(QMainWindow):
    start_requested = Signal()
    stop_requested = Signal()
    api_check_requested = Signal()
    model_download_requested = Signal(str)

    def __init__(self, config_path: Path, overlay) -> None:
        super().__init__()
        self.config_path = config_path
        self.config = AppConfig.load(config_path)
        self.overlay = overlay
        self._running = False
        self._api_verified = False
        self._model_ready = False
        self.setWindowTitle("Tawil Translate · Control Center")
        self.resize(860, 760)
        self.setMinimumSize(760, 620)
        self.setStyleSheet(STYLE)

        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(28, 24, 28, 28)
        page_layout.setSpacing(16)
        title = QLabel("TAWIL TRANSLATE")
        title.setObjectName("title")
        page_layout.addWidget(title)
        subtitle = QLabel("PROCESS AUDIO  /  LOCAL STT  /  STREAM TRANSLATION")
        subtitle.setObjectName("subtitle")
        page_layout.addWidget(subtitle)

        page_layout.addWidget(self._build_api_card())
        page_layout.addWidget(self._build_stt_card())
        page_layout.addWidget(self._build_capture_card())
        page_layout.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.setCentralWidget(scroll)
        self._refresh_processes()
        self._update_profile()
        self._refresh_start_state()
        self.statusBar().showMessage("等待配置")

    def _card(self, title: str, step: str) -> tuple[QFrame, QVBoxLayout]:
        card = QFrame()
        card.setObjectName("card")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(20, 18, 20, 20)
        layout.setSpacing(12)
        heading = QHBoxLayout()
        label = QLabel(title)
        label.setObjectName("section")
        badge = QLabel(step)
        badge.setStyleSheet("color:#59b5ff;background:#102a42;padding:3px 8px;border-radius:8px")
        heading.addWidget(label)
        heading.addStretch()
        heading.addWidget(badge)
        layout.addLayout(heading)
        return card, layout

    def _build_api_card(self) -> QFrame:
        card, layout = self._card("翻译服务", "STEP 01")
        self.api_base = QLineEdit(self.config.translation.base_url)
        self.api_base.setPlaceholderText("https://api.example.com/v1")
        layout.addWidget(self._field("OpenAI 兼容 API 地址", self.api_base))
        self.api_key = QLineEdit()
        self.api_key.setEchoMode(QLineEdit.Password)
        has_key = bool(get_api_key(self.config.translation.api_key_env))
        self.api_key.setPlaceholderText("已安全保存密钥" if has_key else "输入 API Key")
        layout.addWidget(self._field("API Key · 保存至 Windows 凭据管理器", self.api_key))
        check_row = QHBoxLayout()
        self.api_state = QLabel("尚未检查")
        self.api_state.setObjectName("hint")
        self.check_api_button = QPushButton("保存并检查连接")
        self.check_api_button.clicked.connect(self._save_and_check_api)
        check_row.addWidget(self.api_state, 1)
        check_row.addWidget(self.check_api_button)
        layout.addLayout(check_row)
        self.translation_model = QComboBox()
        self.translation_model.setEnabled(False)
        if self.config.translation.model:
            self.translation_model.addItem(self.config.translation.model)
        layout.addWidget(self._field("连接成功后选择服务端提供的模型", self.translation_model))
        self.api_base.textChanged.connect(self._invalidate_api)
        return card

    def _build_stt_card(self) -> QFrame:
        card, layout = self._card("本地语音识别", "STEP 02")
        row = QHBoxLayout()
        self.profile = QComboBox()
        for item in PROFILES:
            vram = "CPU" if item.device == "cpu" else f"显存约 {item.approximate_vram_gb:.1f}GB"
            self.profile.addItem(f"{item.label}  ·  {vram}", item.id)
        self.profile.setCurrentIndex(max(0, self.profile.findData(self.config.stt.profile)))
        self.profile.currentIndexChanged.connect(self._update_profile)
        self.download_button = QPushButton("下载所选模型")
        self.download_button.clicked.connect(
            lambda: self.model_download_requested.emit(self.profile.currentData())
        )
        row.addWidget(self.profile, 1)
        row.addWidget(self.download_button)
        layout.addLayout(row)
        self.profile_detail = QLabel()
        self.profile_detail.setObjectName("hint")
        self.profile_detail.setWordWrap(True)
        layout.addWidget(self.profile_detail)
        vram = detect_cuda_vram_gb()
        recommended = recommend_profile(vram, vram is not None)
        hardware = "未检测到 NVIDIA GPU" if vram is None else f"检测到约 {vram:.1f}GB NVIDIA 显存"
        recommendation = QLabel(f"{hardware}  ·  推荐 {recommended.label}")
        recommendation.setObjectName("hint")
        layout.addWidget(recommendation)
        self.model_progress = QProgressBar()
        self.model_progress.setRange(0, 0)
        self.model_progress.hide()
        layout.addWidget(self.model_progress)
        self.model_state = QLabel()
        self.model_state.setObjectName("hint")
        layout.addWidget(self.model_state)
        return card

    def _build_capture_card(self) -> QFrame:
        card, layout = self._card("捕获与悬浮窗", "STEP 03")
        process_row = QHBoxLayout()
        self.process = QComboBox()
        refresh = QPushButton("刷新进程")
        refresh.clicked.connect(self._refresh_processes)
        process_row.addWidget(self.process, 1)
        process_row.addWidget(refresh)
        layout.addWidget(self._field("当前有声音的游戏 / 直播进程", process_row))
        self.process_state = QLabel("只显示具有活跃 Windows 音频会话的进程")
        self.process_state.setObjectName("hint")
        layout.addWidget(self.process_state)
        display_row = QHBoxLayout()
        self.opacity = QSlider(Qt.Horizontal)
        self.opacity.setRange(30, 100)
        self.opacity.setValue(round(self.config.overlay.opacity * 100))
        self.opacity.valueChanged.connect(lambda value: self.overlay.setWindowOpacity(value / 100))
        self.click_through = QCheckBox("启动后穿透鼠标")
        self.click_through.setChecked(self.config.overlay.click_through)
        display_row.addWidget(QLabel("透明度"))
        display_row.addWidget(self.opacity, 1)
        display_row.addWidget(self.click_through)
        layout.addLayout(display_row)
        actions = QHBoxLayout()
        preview = QPushButton("预览悬浮窗")
        preview.clicked.connect(self.overlay.show)
        save = QPushButton("保存设置")
        save.clicked.connect(self._save_all)
        self.start_stop = QPushButton("开始翻译")
        self.start_stop.setObjectName("primary")
        self.start_stop.clicked.connect(self._toggle_running)
        actions.addWidget(preview)
        actions.addStretch()
        actions.addWidget(save)
        actions.addWidget(self.start_stop)
        layout.addLayout(actions)
        self.start_hint = QLabel()
        self.start_hint.setObjectName("hint")
        layout.addWidget(self.start_hint)
        return card

    def _field(self, label: str, control) -> QWidget:
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        caption = QLabel(label)
        caption.setObjectName("hint")
        layout.addWidget(caption)
        if isinstance(control, QHBoxLayout):
            layout.addLayout(control)
        else:
            layout.addWidget(control)
        return container

    def _save_api(self) -> None:
        self.config.translation.base_url = self.api_base.text().strip()
        if self.api_key.text():
            set_api_key(self.config.translation.api_key_env, self.api_key.text())
            self.api_key.clear()
            self.api_key.setPlaceholderText("已安全保存密钥")
        self.config.save(self.config_path)

    def _save_and_check_api(self) -> None:
        self._save_api()
        self.check_api_button.setEnabled(False)
        self.api_state.setText("正在连接并读取模型列表…")
        self.api_state.setObjectName("hint")
        self.api_state.style().polish(self.api_state)
        self.api_check_requested.emit()

    def set_api_models(self, models: list[str]) -> None:
        self.translation_model.clear()
        self.translation_model.addItems(models)
        preferred = self.translation_model.findText(self.config.translation.model)
        self.translation_model.setCurrentIndex(max(0, preferred))
        self.translation_model.setEnabled(True)
        self.check_api_button.setEnabled(True)
        self._api_verified = True
        self.api_state.setText(f"连接正常 · 发现 {len(models)} 个模型")
        self.api_state.setObjectName("success")
        self.api_state.style().polish(self.api_state)
        self._refresh_start_state()

    def set_api_error(self, detail: str) -> None:
        self.check_api_button.setEnabled(True)
        self._api_verified = False
        self.translation_model.setEnabled(False)
        self.api_state.setText(f"连接失败 · {detail}")
        self.api_state.setObjectName("error")
        self.api_state.style().polish(self.api_state)
        self._refresh_start_state()

    def _invalidate_api(self) -> None:
        self._api_verified = False
        if hasattr(self, "translation_model"):
            self.translation_model.setEnabled(False)
        self._refresh_start_state()

    def _update_profile(self) -> None:
        if not hasattr(self, "profile_detail"):
            return
        profile = PROFILES[self.profile.currentIndex()]
        self.config.stt.profile = profile.id
        manager = LocalModelManager(model_root(self.config.stt.model_dir))
        self._model_ready = manager.is_downloaded(profile)
        self.profile_detail.setText(
            f"{profile.use_case} · 下载约 {profile.approximate_download_gb:.2f}GB · "
            f"{profile.compute_type}"
        )
        location = manager.path_for(profile)
        self.model_state.setText(
            f"模型已下载 · {location}" if self._model_ready else f"尚未下载 · 将保存到 {location}"
        )
        self.model_state.setToolTip(str(location))
        self.model_state.setObjectName("success" if self._model_ready else "hint")
        self.model_state.style().polish(self.model_state)
        self.download_button.setText("重新下载" if self._model_ready else "下载所选模型")
        self._refresh_start_state()

    def set_model_downloading(self, downloading: bool) -> None:
        self.model_progress.setVisible(downloading)
        self.download_button.setEnabled(not downloading)
        self.profile.setEnabled(not downloading)
        if downloading:
            self.model_state.setText("正在下载模型文件，请勿关闭程序…")

    def set_model_downloaded(self, profile_id: str) -> None:
        self.set_model_downloading(False)
        if self.profile.currentData() == profile_id:
            self._update_profile()

    def set_model_error(self, detail: str) -> None:
        self.set_model_downloading(False)
        self.model_state.setText(f"下载失败 · {detail}")
        self.model_state.setObjectName("error")
        self.model_state.style().polish(self.model_state)

    def _save_all(self) -> None:
        self._save_api()
        self.config.stt.profile = self.profile.currentData()
        if self.translation_model.isEnabled() and self.translation_model.currentText():
            self.config.translation.model = self.translation_model.currentText()
        self.config.overlay.opacity = self.opacity.value() / 100
        self.config.overlay.click_through = self.click_through.isChecked()
        selected = self.process.currentData()
        if selected:
            self.config.audio.target_pid = selected.pid
            self.config.audio.target_executable = selected.name
        self.config.save(self.config_path)
        self.overlay.set_edit_mode(not self.config.overlay.click_through)
        self.statusBar().showMessage("设置已保存", 3000)

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
        for process in processes:
            self.process.addItem(process.label, process)
            if process.pid == remembered:
                self.process.setCurrentIndex(self.process.count() - 1)
        self.process_state.setText(
            f"发现 {len(processes)} 个有声音的进程"
            if processes
            else "暂未发现有声音的进程 · 请先让游戏或直播播放声音，再点击刷新"
        )
        self.process_state.setObjectName("success" if processes else "hint")
        self.process_state.style().polish(self.process_state)
        self._refresh_start_state()

    def _toggle_running(self) -> None:
        if self._running:
            self.stop_requested.emit()
            return
        self._save_all()
        self.start_requested.emit()

    def _refresh_start_state(self) -> None:
        if not hasattr(self, "start_stop"):
            return
        has_process = self.process.currentData() is not None
        ready = self._api_verified and self._model_ready and has_process
        self.start_stop.setEnabled(self._running or ready)
        missing = []
        if not self._api_verified:
            missing.append("检查翻译 API")
        if not self._model_ready:
            missing.append("下载本地语音模型")
        if not has_process:
            missing.append("播放声音后刷新并选择目标进程")
        self.start_hint.setText("准备就绪" if not missing else "开始前需要：" + "、".join(missing))

    def set_running(self, running: bool) -> None:
        self._running = running
        self.start_stop.setText("停止翻译" if running else "开始翻译")
        self.profile.setEnabled(not running)
        self.process.setEnabled(not running)
        self._refresh_start_state()

    def set_status(self, state: str, detail: str) -> None:
        colors = {
            "listening": "#48d597",
            "working": "#48a9ff",
            "error": "#ff6978",
            "degraded": "#ffb84d",
        }
        self.statusBar().setStyleSheet(f"color:{colors.get(state, '#8292a8')}")
        self.statusBar().showMessage(detail or state)
        if state == "working" and "下载" in detail:
            self.set_model_downloading(True)
