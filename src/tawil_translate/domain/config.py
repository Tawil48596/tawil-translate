from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TRANSLATION_PROMPT = """你是专业的游戏与直播实时字幕翻译器。请将输入内容翻译为{target_language}。
要求：只输出译文，不解释、不添加前缀；保持人物语气、情绪、数字和格式；结合最近上下文消解指代；专有名词严格遵循词库；听写不完整时优先给出自然、简洁且适合字幕阅读的译文。
词库约束：{glossary}"""


@dataclass(slots=True)
class AudioConfig:
    target_pid: int | None = None
    target_executable: str | None = None
    sample_rate: int = 16_000
    frame_ms: int = 20
    helper_path: str = "bin/tawil-audio-capture.exe"


@dataclass(slots=True)
class STTConfig:
    profile: str = "balanced"
    model: str | None = None
    device: str = "auto"
    compute_type: str = "auto"
    source_language: str | None = None
    model_dir: str = "models"
    download_source: str = "auto"


@dataclass(slots=True)
class VADConfig:
    provider: str = "silero"
    threshold: float = 0.5
    min_silence_ms: int = 280
    min_speech_ms: int = 180


@dataclass(slots=True)
class TranslationConfig:
    enabled: bool = True
    provider: str = "openai-compatible"
    base_url: str = "https://api.openai.com/v1"
    model: str = "gpt-4.1-mini"
    api_key_env: str = "TAWIL_API_KEY"
    target_language: str = "zh-CN"
    daily_token_limit: int = 100_000
    timeout_seconds: float = 12.0
    custom_prompt: str = DEFAULT_TRANSLATION_PROMPT


@dataclass(slots=True)
class PipelineConfig:
    queue_size: int = 6
    context_size: int = 6
    overflow_policy: str = "drop_oldest"
    max_segment_seconds: float = 8.0
    merge_gap_ms: int = 260


@dataclass(slots=True)
class OverlayConfig:
    opacity: float = 0.86
    click_through: bool = True
    hotkey: str = "Ctrl+Shift+T"
    max_lines: int = 4


@dataclass(slots=True)
class AppConfig:
    audio: AudioConfig = field(default_factory=AudioConfig)
    vad: VADConfig = field(default_factory=VADConfig)
    stt: STTConfig = field(default_factory=STTConfig)
    translation: TranslationConfig = field(default_factory=TranslationConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    overlay: OverlayConfig = field(default_factory=OverlayConfig)

    @classmethod
    def load(cls, path: Path) -> AppConfig:
        if not path.exists():
            return cls()
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            audio=AudioConfig(**raw.get("audio", {})),
            vad=VADConfig(**raw.get("vad", {})),
            stt=STTConfig(**raw.get("stt", {})),
            translation=TranslationConfig(**raw.get("translation", {})),
            pipeline=PipelineConfig(**raw.get("pipeline", {})),
            overlay=OverlayConfig(**raw.get("overlay", {})),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def api_key(self) -> str:
        return os.environ.get(self.translation.api_key_env, "")
