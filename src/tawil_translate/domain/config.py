from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

DEFAULT_TRANSLATION_PROMPT = """你是实时游戏与直播字幕翻译器。把输入翻译为{target_language}。
只输出简洁、自然的译文，不解释、不加前缀；保留语气、数字与格式。
严格使用这些术语：{glossary}"""

_BROKEN_PROMPT_MARKERS = ("浣犳槸", "缈昏瘧", "璇嶅簱")


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
    min_silence_ms: int = 450
    min_speech_ms: int = 200


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
    first_token_timeout_seconds: float = 1.5
    total_timeout_seconds: float = 3.0
    concurrency: int = 3
    custom_prompt: str = DEFAULT_TRANSLATION_PROMPT


@dataclass(slots=True)
class PipelineConfig:
    queue_size: int = 6
    context_size: int = 6
    overflow_policy: str = "drop_oldest"
    max_segment_seconds: float = 12.0
    merge_gap_ms: int = 260
    preview_interval_ms: int = 1200
    preview_min_speech_ms: int = 900


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
        # Accept settings written by Windows tools that add a UTF-8 BOM.
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8-sig"))
        config = cls(
            audio=AudioConfig(**raw.get("audio", {})),
            vad=VADConfig(**raw.get("vad", {})),
            stt=STTConfig(**raw.get("stt", {})),
            translation=TranslationConfig(**raw.get("translation", {})),
            pipeline=PipelineConfig(**raw.get("pipeline", {})),
            overlay=OverlayConfig(**raw.get("overlay", {})),
        )
        if any(marker in config.translation.custom_prompt for marker in _BROKEN_PROMPT_MARKERS):
            config.translation.custom_prompt = DEFAULT_TRANSLATION_PROMPT
        # Migrate the old low-latency tuning that split normal sentences at
        # 5 seconds and treated brief intra-sentence pauses as sentence ends.
        if config.vad.min_silence_ms <= 280:
            config.vad.min_silence_ms = 450
        config.vad.min_speech_ms = max(config.vad.min_speech_ms, 200)
        if config.pipeline.max_segment_seconds <= 8:
            config.pipeline.max_segment_seconds = 12.0
        if config.translation.concurrency <= 2:
            config.translation.concurrency = 3
        if config.translation.first_token_timeout_seconds >= 4:
            config.translation.first_token_timeout_seconds = 1.5
        if config.translation.total_timeout_seconds >= 7:
            config.translation.total_timeout_seconds = 3.0
        prompt_lines = config.translation.custom_prompt.splitlines()
        if prompt_lines and '"thinking"' in prompt_lines[0]:
            config.translation.custom_prompt = "\n".join(prompt_lines[1:]).lstrip()
        return config

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")

    @property
    def api_key(self) -> str:
        return os.environ.get(self.translation.api_key_env, "")
