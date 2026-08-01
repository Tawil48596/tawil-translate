from __future__ import annotations

import asyncio
from collections import deque
from contextlib import suppress
from time import monotonic
from uuid import uuid4

from tawil_translate.domain.models import (
    HealthEvent,
    HealthState,
    MetricEvent,
    SpeechSegment,
    SubtitleEvent,
)
from tawil_translate.domain.ports import (
    AudioSource,
    EventHandler,
    STTEngine,
    Translator,
    VoiceActivityDetector,
)

from .budget import BudgetExceeded, DailyTokenBudget
from .chunking import SmartChunker
from .circuit_breaker import CircuitBreaker, CircuitOpen


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
        overflow_policy: str = "drop_oldest",
        chunker: SmartChunker | None = None,
        circuit_breaker: CircuitBreaker | None = None,
    ) -> None:
        self.audio = audio
        self.vad = vad
        self.stt = stt
        self.translator = translator
        self.emit = emit
        self.glossary = glossary or {}
        self.budget = budget or DailyTokenBudget(100_000)
        if overflow_policy not in {"wait", "drop_oldest"}:
            raise ValueError("overflow_policy must be 'wait' or 'drop_oldest'")
        self.overflow_policy = overflow_policy
        self.segments: asyncio.Queue[SpeechSegment | None] = asyncio.Queue(maxsize=queue_size)
        self.context: deque[str] = deque(maxlen=context_size)
        self.chunker = chunker
        self.circuit_breaker = circuit_breaker or CircuitBreaker()

    async def run(self) -> None:
        await self.emit(HealthEvent("stt", HealthState.WORKING, "warming up model"))
        await self.stt.warmup()
        await self.emit(HealthEvent("stt", HealthState.IDLE, "model ready"))
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
            await self.stt.close()

    async def _capture(self) -> None:
        await self.emit(HealthEvent("audio", HealthState.LISTENING))
        async for frame in self.audio.frames():
            for segment in await self.vad.feed(frame):
                outputs = self.chunker.push(segment) if self.chunker else [segment]
                for output in outputs:
                    await self._enqueue(output)
        for segment in await self.vad.flush():
            outputs = self.chunker.push(segment) if self.chunker else [segment]
            for output in outputs:
                await self._enqueue(output)
        if self.chunker:
            for output in self.chunker.flush():
                await self._enqueue(output)
        await self.segments.put(None)

    async def _enqueue(self, segment: SpeechSegment) -> None:
        if self.overflow_policy == "wait" or not self.segments.full():
            await self.segments.put(segment)
            return
        self.segments.get_nowait()
        self.segments.task_done()
        await self.emit(
            HealthEvent("pipeline", HealthState.DEGRADED, "latency guard dropped oldest segment")
        )
        await self.segments.put(segment)

    async def _recognize(self) -> None:
        while True:
            segment = await self.segments.get()
            if segment is None:
                self.segments.task_done()
                return
            try:
                started = monotonic()
                await self.emit(HealthEvent("stt", HealthState.WORKING))
                transcript = await self.stt.transcribe(segment)
                if not transcript.text.strip():
                    continue
                utterance_id = transcript.utterance_id or uuid4().hex
                self.budget.reserve(self.budget.estimate(transcript.text))
                self.circuit_breaker.before_call()
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
                self.circuit_breaker.success()
                self.context.append(transcript.text)
                latency_ms = round((monotonic() - started) * 1000)
                await self.emit(
                    SubtitleEvent(
                        utterance_id, transcript.text, rendered, is_final=True, latency_ms=latency_ms
                    )
                )
                await self.emit(MetricEvent("end_to_end_latency", latency_ms, "ms"))
            except BudgetExceeded as exc:
                await self.emit(HealthEvent("translator", HealthState.ERROR, str(exc)))
                return
            except CircuitOpen as exc:
                await self.emit(HealthEvent("translator", HealthState.DEGRADED, str(exc)))
            except Exception as exc:  # noqa: BLE001 - adapter failures must become UI events
                # Error events keep the overlay non-blocking; production code adds retry policy here.
                self.circuit_breaker.failure()
                await self.emit(HealthEvent("pipeline", HealthState.ERROR, str(exc)))
            finally:
                self.segments.task_done()
