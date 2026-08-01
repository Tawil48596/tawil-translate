from __future__ import annotations

from tawil_translate.domain.config import STTConfig
from tawil_translate.domain.ports import STTEngine
from tawil_translate.infrastructure.faster_whisper_stt import FasterWhisperSTT

from .model_catalog import STTProfile, get_profile


def resolve_stt_profile(config: STTConfig) -> STTProfile:
    base = get_profile(config.profile)
    if not any((config.model, config.device != "auto", config.compute_type != "auto")):
        return base
    return STTProfile(
        id="custom",
        label="自定义",
        model=config.model or base.model,
        device=base.device if config.device == "auto" else config.device,
        compute_type=base.compute_type if config.compute_type == "auto" else config.compute_type,
        approximate_vram_gb=base.approximate_vram_gb,
        use_case="用户自定义配置",
    )


def build_stt(config: STTConfig) -> STTEngine:
    return FasterWhisperSTT(resolve_stt_profile(config), config.model_dir, config.source_language)
