from __future__ import annotations

import argparse
import asyncio

from tawil_translate.application.pipeline import TranslationPipeline
from tawil_translate.domain.models import HealthEvent, SubtitleEvent
from tawil_translate.infrastructure.demo import DemoAudioSource, DemoSTT, DemoTranslator, DemoVAD


async def _print_event(event: object) -> None:
    if isinstance(event, SubtitleEvent):
        # Keep the CLI usable on legacy Windows consoles whose active code page is GBK.
        marker = "OK" if event.is_final else ".."
        print(f"\r{marker} {event.source_text} → {event.translated_text}", end="\n" if event.is_final else "")
    elif isinstance(event, HealthEvent):
        print(f"[{event.component}] {event.state.value} {event.detail}")


async def _demo() -> None:
    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=DemoSTT(),
        translator=DemoTranslator(),
        emit=_print_event,
    )
    await pipeline.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tawil Translate")
    parser.add_argument("--demo", action="store_true", help="run the dependency-free demo pipeline")
    args = parser.parse_args()
    if not args.demo:
        parser.error("the desktop adapter is not wired yet; use --demo")
    asyncio.run(_demo())
