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
        translator: Translator | None,
        emit: EventHandler,
        glossary: dict[str, str] | None = None,
        budget: DailyTokenBudget | None = None,
        queue_size: int = 8,
        context_size: int = 6,
        overflow_policy: str = "drop_oldest",
        chunker: SmartChunker | None = None,
        circuit_breaker: CircuitBreaker | None = None,
        translation_enabled: bool = True,
    ) -> None:
        self.audio = audio
        self.vad = vad
        self.stt = stt
        self.translator = translator
        self.translation_enabled = translation_enabled
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
        self._translation_tasks: set[asyncio.Task[None]] = set()
        self._translation_slots = asyncio.Semaphore(2)

    async def run(self) -> None:
        await self.emit(HealthEvent("vad", HealthState.WORKING, "正在加载语音活动检测…"))
        await asyncio.wait_for(self.vad.warmup(), timeout=60)
        await self.emit(HealthEvent("stt", HealthState.WORKING, "正在加载本地语音模型…"))
        await asyncio.wait_for(self.stt.warmup(), timeout=240)
        await self.emit(HealthEvent("stt", HealthState.IDLE, "model ready"))
        capture = asyncio.create_task(self._capture(), name="audio-capture")
        recognize = asyncio.create_task(self._recognize(), name="stt-translate")
        cancelled = False
        try:
            await asyncio.gather(capture, recognize)
        except asyncio.CancelledError:
            cancelled = True
            raise
        finally:
            for task in (capture, recognize):
                task.cancel()
            for task in (capture, recognize):
                with suppress(asyncio.CancelledError):
                    await task
            if cancelled:
                for task in tuple(self._translation_tasks):
                    task.cancel()
            if self._translation_tasks:
                await asyncio.gather(*self._translation_tasks, return_exceptions=True)
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
                await self.emit(
                    SubtitleEvent(utterance_id, transcript.text, "", is_final=False)
                )
                context = tuple(self.context)
                self.context.append(transcript.text)
                if not self.translation_enabled or self.translator is None:
                    latency_ms = round((monotonic() - started) * 1000)
                    await self.emit(
                        SubtitleEvent(
                            utterance_id,
                            transcript.text,
                            "",
                            is_final=True,
                            latency_ms=latency_ms,
                        )
                    )
                    await self.emit(MetricEvent("caption_latency", latency_ms, "ms"))
                    continue
                self._schedule_translation(
                    transcript.text, utterance_id, context=context, started=started
                )
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

    def _schedule_translation(
        self, text: str, utterance_id: str, *, context: tuple[str, ...], started: float
    ) -> None:
        for task in tuple(self._translation_tasks):
            if task.done():
                self._translation_tasks.discard(task)
        # Keep at most two live requests. Under sustained API slowness, stale
        # translation is cancelled so it cannot build an ever-growing delay.
        if len(self._translation_tasks) >= 2:
            oldest = min(self._translation_tasks, key=lambda task: task.get_name())
            oldest.cancel()
        task = asyncio.create_task(
            self._translate_one(text, utterance_id, context=context, started=started),
            name=f"translate-{monotonic():020.6f}",
        )
        self._translation_tasks.add(task)
        task.add_done_callback(self._translation_tasks.discard)

    async def _translate_one(
        self, text: str, utterance_id: str, *, context: tuple[str, ...], started: float
    ) -> None:
        try:
            async with self._translation_slots:
                self.budget.reserve(self.budget.estimate(text))
                self.circuit_breaker.before_call()
                rendered = ""
                assert self.translator is not None
                async for delta in self.translator.translate(
                    text, context=context, glossary=self.glossary
                ):
                    rendered += delta
                    await self.emit(SubtitleEvent(utterance_id, text, rendered, is_final=False))
                self.circuit_breaker.success()
                latency_ms = round((monotonic() - started) * 1000)
                await self.emit(
                    SubtitleEvent(utterance_id, text, rendered, is_final=True, latency_ms=latency_ms)
                )
                await self.emit(MetricEvent("end_to_end_latency", latency_ms, "ms"))
        except asyncio.CancelledError:
            raise
        except BudgetExceeded as exc:
            await self.emit(HealthEvent("translator", HealthState.ERROR, str(exc)))
        except CircuitOpen as exc:
            await self.emit(HealthEvent("translator", HealthState.DEGRADED, str(exc)))
        except Exception as exc:  # noqa: BLE001 - background API boundary
            self.circuit_breaker.failure()
            await self.emit(HealthEvent("translator", HealthState.ERROR, str(exc)))
