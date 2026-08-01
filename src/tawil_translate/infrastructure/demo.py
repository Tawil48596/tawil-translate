from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from typing import ClassVar
from uuid import uuid4

from tawil_translate.domain.models import AudioFrame, SpeechSegment, Transcript


class DemoAudioSource:
    async def frames(self) -> AsyncIterator[AudioFrame]:
        for text in ("Welcome to the arena", "The objective is under attack"):
            await asyncio.sleep(0.05)
            yield AudioFrame(text.encode(), 16_000, 1)


class DemoVAD:
    async def feed(self, frame: AudioFrame) -> list[SpeechSegment]:
        return [SpeechSegment(frame.pcm, frame.sample_rate, frame.captured_at, frame.captured_at)]

    async def flush(self) -> list[SpeechSegment]:
        return []


class DemoSTT:
    async def warmup(self) -> None:
        return None

    async def transcribe(self, segment: SpeechSegment) -> Transcript:
        return Transcript(uuid4().hex, segment.audio.decode(), "en")

    async def close(self) -> None:
        return None


class DemoTranslator:
    _translations: ClassVar[dict[str, str]] = {
        "Welcome to the arena": "欢迎来到竞技场",
        "The objective is under attack": "目标正在遭受攻击",
    }

    async def translate(
        self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
    ) -> AsyncIterator[str]:
        translated = self._translations.get(text, text)
        for character in translated:
            await asyncio.sleep(0.005)
            yield character
