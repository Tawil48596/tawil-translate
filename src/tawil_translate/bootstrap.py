from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from tawil_translate.application.model_catalog import PROFILES
from tawil_translate.application.pipeline import TranslationPipeline
from tawil_translate.domain.config import AppConfig
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
        chunker=None,
    )
    await pipeline.run()


def main() -> None:
    parser = argparse.ArgumentParser(description="Tawil Translate")
    parser.add_argument("--demo", action="store_true", help="run the dependency-free demo pipeline")
    parser.add_argument("--desktop", action="store_true", help="open the unified desktop settings and overlay")
    parser.add_argument("--list-models", action="store_true", help="show local STT options")
    parser.add_argument("--profile", choices=[profile.id for profile in PROFILES])
    parser.add_argument("--config", type=Path, default=Path("configs/user_config.json"))
    args = parser.parse_args()
    if args.list_models:
        print("ID        VRAM     Model             Best for")
        for profile in PROFILES:
            vram = "CPU" if profile.device == "cpu" else f"~{profile.approximate_vram_gb:.1f} GB"
            print(f"{profile.id:<9} {vram:<8} {profile.model:<17} {profile.use_case}")
        return
    config = AppConfig.load(args.config)
    if args.profile:
        config.stt.profile = args.profile
        config.save(args.config)
        print(f"Saved STT profile: {args.profile}")
    if args.desktop:
        try:
            from tawil_translate.ui.app import run_desktop
        except ImportError as exc:
            parser.error(f'PySide6 is required; install with: pip install -e ".[desktop]" ({exc})')
        raise SystemExit(run_desktop(args.config))
    if not args.demo:
        parser.error("choose --desktop, --demo or --list-models")
    asyncio.run(_demo())
