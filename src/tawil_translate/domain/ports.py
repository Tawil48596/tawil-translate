from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Protocol

from .models import AudioFrame, SpeechSegment, Transcript


class AudioSource(Protocol):
    def frames(self) -> AsyncIterator[AudioFrame]: ...


class VoiceActivityDetector(Protocol):
    async def warmup(self) -> None: ...
    async def feed(self, frame: AudioFrame) -> list[SpeechSegment]: ...
    async def flush(self) -> list[SpeechSegment]: ...


class STTEngine(Protocol):
    async def warmup(self) -> None: ...
    async def transcribe(self, segment: SpeechSegment) -> Transcript: ...

    async def close(self) -> None: ...


class Translator(Protocol):
    def translate(
        self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
    ) -> AsyncIterator[str]: ...


EventHandler = Callable[[object], Awaitable[None]]
