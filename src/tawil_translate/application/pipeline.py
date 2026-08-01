from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from uuid import uuid4

from tawil_translate.domain.models import HealthEvent, HealthState, SubtitleEvent
from tawil_translate.domain.ports import (
    AudioSource,
    EventHandler,
    STTEngine,
    Translator,
    VoiceActivityDetector,
)

from .budget import BudgetExceeded, DailyTokenBudget


class TranslationPipeline:
    """Bounded, cancellable producer-consumer pipeline independent from Qt."""

    def __init__(
        self,
        *,
        audio: AudioSource,
        vad: VoiceActivityDetector,
        stt: STTEngine,
        translator: Translator,
        emit: EventHandler,
        glossary: dict[str, str] | None = None,
        budget: DailyTokenBudget | None = None,
        queue_size: int = 8,
        context_size: int = 6,
    ) -> None:
        self.audio = audio
        self.vad = vad
        self.stt = stt
        self.translator = translator
        self.emit = emit
        self.glossary = glossary or {}
        self.budget = budget or DailyTokenBudget(100_000)
        self.segments: asyncio.Queue = asyncio.Queue(maxsize=queue_size)
        self.context: deque[str] = deque(maxlen=context_size)

    async def run(self) -> None:
        capture = asyncio.create_task(self._capture(), name="audio-capture")
        recognize = asyncio.create_task(self._recognize(), name="stt-translate")
        try:
            await asyncio.gather(capture, recognize)
        finally:
            for task in (capture, recognize):
                task.cancel()
            for task in (capture, recognize):
                with suppress(asyncio.CancelledError):
                    await task

    async def _capture(self) -> None:
        await self.emit(HealthEvent("audio", HealthState.LISTENING))
        async for frame in self.audio.frames():
            for segment in await self.vad.feed(frame):
                await self.segments.put(segment)  # backpressure is intentional
        for segment in await self.vad.flush():
            await self.segments.put(segment)
        await self.segments.put(None)

    async def _recognize(self) -> None:
        while True:
            segment = await self.segments.get()
            if segment is None:
                return
            try:
                await self.emit(HealthEvent("stt", HealthState.WORKING))
                transcript = await self.stt.transcribe(segment)
                if not transcript.text.strip():
                    continue
                utterance_id = transcript.utterance_id or uuid4().hex
                self.budget.reserve(self.budget.estimate(transcript.text))
                rendered = ""
                async for delta in self.translator.translate(
                    transcript.text,
                    context=tuple(self.context),
                    glossary=self.glossary,
                ):
                    rendered += delta
                    await self.emit(
                        SubtitleEvent(utterance_id, transcript.text, rendered, is_final=False)
                    )
                self.context.append(transcript.text)
                await self.emit(
                    SubtitleEvent(utterance_id, transcript.text, rendered, is_final=True)
                )
            except BudgetExceeded as exc:
                await self.emit(HealthEvent("translator", HealthState.ERROR, str(exc)))
                return
            except Exception as exc:
                # Error events keep the overlay non-blocking; production code adds retry policy here.
                await self.emit(HealthEvent("pipeline", HealthState.ERROR, str(exc)))
            finally:
                self.segments.task_done()

