from __future__ import annotations

import json
from pathlib import Path

from tawil_translate.domain.config import AppConfig
from tawil_translate.domain.ports import EventHandler
from tawil_translate.infrastructure.energy_vad import EnergyVAD
from tawil_translate.infrastructure.openai_translator import OpenAICompatibleTranslator
from tawil_translate.infrastructure.process_loopback import ProcessLoopbackSource

from .budget import DailyTokenBudget
from .chunking import SmartChunker
from .pipeline import TranslationPipeline
from .runtime import build_stt


def build_pipeline(config: AppConfig, emit: EventHandler, root: Path) -> TranslationPipeline:
    if not config.audio.target_pid:
        raise ValueError("select a target process before starting")
    glossary_path = root / "configs" / "glossary.json"
    glossary = json.loads(glossary_path.read_text(encoding="utf-8")) if glossary_path.exists() else {}
    audio = ProcessLoopbackSource(
        pid=config.audio.target_pid,
        helper_path=root / config.audio.helper_path,
        frame_ms=config.audio.frame_ms,
    )
    translator = OpenAICompatibleTranslator(
        base_url=config.translation.base_url,
        model=config.translation.model,
        api_key=config.api_key,
        target_language=config.translation.target_language,
        timeout_seconds=config.translation.timeout_seconds,
    )
    return TranslationPipeline(
        audio=audio,
        vad=EnergyVAD(),
        stt=build_stt(config.stt),
        translator=translator,
        emit=emit,
        glossary=glossary,
        budget=DailyTokenBudget(config.translation.daily_token_limit),
        queue_size=config.pipeline.queue_size,
        context_size=config.pipeline.context_size,
        overflow_policy=config.pipeline.overflow_policy,
        chunker=SmartChunker(
            merge_gap_ms=config.pipeline.merge_gap_ms,
            max_seconds=config.pipeline.max_segment_seconds,
        ),
    )
