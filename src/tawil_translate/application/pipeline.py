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
    Transcript,
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
        translation_concurrency: int = 3,
        first_token_timeout: float = 1.5,
        translation_timeout: float = 3.0,
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
        self.preview_segments: asyncio.Queue[SpeechSegment | None] = asyncio.Queue(maxsize=1)
        self.preview_transcripts: asyncio.Queue[tuple[str, tuple[str, ...]] | None] = (
            asyncio.Queue(maxsize=1)
        )
        self.translation_concurrency = max(1, min(translation_concurrency, 4))
        self.first_token_timeout = max(0.05, first_token_timeout)
        self.translation_timeout = max(self.first_token_timeout, translation_timeout)
        self.transcripts: asyncio.Queue[
            tuple[Transcript, float, tuple[str, ...]] | None
        ] = asyncio.Queue(maxsize=queue_size)
        self.context: deque[str] = deque(maxlen=context_size)
        self.chunker = chunker
        self.circuit_breaker = circuit_breaker or CircuitBreaker()
        self._last_finalized_started = float("-inf")
        self._preview_text = ""
        self._preview_translation_source = ""
        self._speculative_cache: dict[str, str] = {}

    async def run(self) -> None:
        await self.emit(HealthEvent("vad", HealthState.WORKING, "正在加载语音活动检测…"))
        await asyncio.wait_for(self.vad.warmup(), timeout=60)
        await self.emit(HealthEvent("stt", HealthState.WORKING, "正在加载本地语音模型…"))
        await asyncio.wait_for(self.stt.warmup(), timeout=240)
        await self.emit(HealthEvent("stt", HealthState.IDLE, "model ready"))
        capture = asyncio.create_task(self._capture(), name="audio-capture")
        recognize = asyncio.create_task(self._recognize(), name="stt")
        preview = asyncio.create_task(self._recognize_preview(), name="stt-preview")
        preview_translate = asyncio.create_task(
            self._translate_preview(), name="translate-preview"
        )
        translate_workers = [
            asyncio.create_task(self._translate_worker(), name=f"translate-{index}")
            for index in range(self.translation_concurrency)
        ]
        tasks = (capture, recognize, preview, preview_translate, *translate_workers)
        try:
            await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                with suppress(asyncio.CancelledError):
                    await task
            await self.stt.close()
            close_translator = getattr(self.translator, "close", None)
            if close_translator is not None:
                await close_translator()

    async def _capture(self) -> None:
        await self.emit(HealthEvent("audio", HealthState.LISTENING))
        async for frame in self.audio.frames():
            for segment in await self.vad.feed(frame):
                if not segment.committed:
                    await self._enqueue_preview(segment)
                    continue
                self._last_finalized_started = max(
                    self._last_finalized_started, segment.started_at
                )
                self._preview_text = ""
                self._preview_translation_source = ""
                outputs = self.chunker.push(segment) if self.chunker else [segment]
                for output in outputs:
                    await self._enqueue(output)
        for segment in await self.vad.flush():
            if not segment.committed:
                await self._enqueue_preview(segment)
                continue
            self._last_finalized_started = max(
                self._last_finalized_started, segment.started_at
            )
            self._preview_text = ""
            self._preview_translation_source = ""
            outputs = self.chunker.push(segment) if self.chunker else [segment]
            for output in outputs:
                await self._enqueue(output)
        if self.chunker:
            for output in self.chunker.flush():
                await self._enqueue(output)
        await self.preview_segments.put(None)
        await self.segments.put(None)

    async def _enqueue_preview(self, segment: SpeechSegment) -> None:
        if self.preview_segments.full():
            previous = self.preview_segments.get_nowait()
            self.preview_segments.task_done()
            if previous is None:
                await self.preview_segments.put(None)
                return
        await self.preview_segments.put(segment)

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
                for _ in range(self.translation_concurrency):
                    await self.transcripts.put(None)
                return
            try:
                started = monotonic()
                await self.emit(HealthEvent("stt", HealthState.WORKING))
                transcript = await self.stt.transcribe(segment)
                if not transcript.text.strip():
                    continue
                if not self.translation_enabled or self.translator is None:
                    utterance_id = transcript.utterance_id or uuid4().hex
                    await self.emit(SubtitleEvent(utterance_id, transcript.text, "", is_final=False))
                    latency_ms = round((monotonic() - started) * 1000)
                    self.context.append(transcript.text)
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
                # Recognition is intentionally independent from the network.
                utterance_id = transcript.utterance_id or uuid4().hex
                await self.emit(SubtitleEvent(utterance_id, transcript.text, "", is_final=False))
                context = tuple(self.context)
                self.context.append(transcript.text)
                cached = self._speculative_cache.pop(transcript.text, "")
                if cached:
                    latency_ms = round((monotonic() - started) * 1000)
                    await self.emit(
                        SubtitleEvent(
                            utterance_id,
                            transcript.text,
                            cached,
                            is_final=True,
                            latency_ms=latency_ms,
                        )
                    )
                    await self.emit(MetricEvent("speculative_cache_hit", 1, "count"))
                    continue
                await self.transcripts.put((transcript, started, context))
            except Exception as exc:  # noqa: BLE001 - adapter failures must become UI events
                await self.emit(HealthEvent("stt", HealthState.ERROR, str(exc)))
            finally:
                self.segments.task_done()

    async def _recognize_preview(self) -> None:
        while True:
            segment = await self.preview_segments.get()
            if segment is None:
                self.preview_segments.task_done()
                await self.preview_transcripts.put(None)
                return
            try:
                transcript = await self.stt.transcribe(segment)
                if (
                    segment.started_at <= self._last_finalized_started
                    or not transcript.text.strip()
                ):
                    continue
                stable = _stable_prefix(self._preview_text, transcript.text)
                self._preview_text = transcript.text
                await self.emit(
                    SubtitleEvent("preview", stable or transcript.text, "", is_final=False)
                )
                if self.translation_enabled and self.translator is not None:
                    await self._enqueue_preview_translation(transcript.text)
            except Exception as exc:  # noqa: BLE001 - preview must never stop final STT
                await self.emit(HealthEvent("stt-preview", HealthState.DEGRADED, str(exc)))
            finally:
                self.preview_segments.task_done()

    async def _enqueue_preview_translation(self, text: str) -> None:
        text = text.strip()
        if len(text) < 4 or text == self._preview_translation_source:
            return
        self._preview_translation_source = text
        if self.preview_transcripts.full():
            self.preview_transcripts.get_nowait()
            self.preview_transcripts.task_done()
        await self.preview_transcripts.put((text, tuple(self.context)))

    async def _translate_preview(self) -> None:
        while True:
            item = await self.preview_transcripts.get()
            if item is None:
                self.preview_transcripts.task_done()
                return
            source, context = item
            try:
                assert self.translator is not None
                rendered = ""
                stream = self.translator.translate(
                    source, context=context, glossary=self.glossary
                ).__aiter__()
                async with asyncio.timeout(min(2.0, self.translation_timeout)):
                    first = await asyncio.wait_for(
                        anext(stream), timeout=min(1.0, self.first_token_timeout)
                    )
                    rendered = first
                    if source == self._preview_translation_source:
                        await self.emit(
                            SubtitleEvent("preview", source, rendered, is_final=False)
                        )
                    async for delta in stream:
                        rendered += delta
                        if source == self._preview_translation_source:
                            await self.emit(
                                SubtitleEvent("preview", source, rendered, is_final=False)
                            )
                if rendered:
                    self._speculative_cache = {source: rendered.strip()}
            except Exception:  # noqa: BLE001,S110 - final translation remains authoritative
                pass
            finally:
                self.preview_transcripts.task_done()

    async def _translate_worker(self) -> None:
        while True:
            item = await self.transcripts.get()
            if item is None:
                self.transcripts.task_done()
                return
            transcript, started, context = item
            utterance_id = transcript.utterance_id or uuid4().hex
            try:
                self.budget.reserve(self.budget.estimate(transcript.text))
                self.circuit_breaker.before_call()
                assert self.translator is not None
                rendered = await self._stream_translation(
                    transcript, utterance_id, context
                )
                self.circuit_breaker.success()
                health = None
            except BudgetExceeded as exc:
                rendered = ""
                health = HealthEvent("translator", HealthState.ERROR, str(exc))
            except CircuitOpen as exc:
                rendered = ""
                health = HealthEvent("translator", HealthState.DEGRADED, str(exc))
            except Exception as exc:  # noqa: BLE001 - network failures stay non-blocking
                self.circuit_breaker.failure()
                rendered = ""
                health = HealthEvent("translator", HealthState.ERROR, str(exc))
            finally:
                self.transcripts.task_done()
            if health is not None:
                await self.emit(health)
            latency_ms = round((monotonic() - started) * 1000)
            await self.emit(
                SubtitleEvent(
                    utterance_id,
                    transcript.text,
                    rendered,
                    is_final=True,
                    latency_ms=latency_ms,
                )
            )
            metric = "end_to_end_latency" if rendered else "caption_latency"
            await self.emit(MetricEvent(metric, latency_ms, "ms"))

    async def _stream_translation(
        self, transcript: Transcript, utterance_id: str, context: tuple[str, ...]
    ) -> str:
        assert self.translator is not None
        stream = self.translator.translate(
            transcript.text, context=context, glossary=self.glossary
        ).__aiter__()
        chunks: list[str] = []
        async with asyncio.timeout(self.translation_timeout):
            try:
                first = await asyncio.wait_for(anext(stream), timeout=self.first_token_timeout)
            except StopAsyncIteration as exc:
                raise RuntimeError("translation API returned an empty response") from exc
            chunks.append(first)
            await self.emit(
                SubtitleEvent(utterance_id, transcript.text, first, is_final=False)
            )
            async for delta in stream:
                chunks.append(delta)
                await self.emit(
                    SubtitleEvent(
                        utterance_id,
                        transcript.text,
                        "".join(chunks),
                        is_final=False,
                    )
                )
        return "".join(chunks).strip()


def _stable_prefix(previous: str, current: str) -> str:
    if not previous:
        return ""
    limit = min(len(previous), len(current))
    index = 0
    while index < limit and previous[index] == current[index]:
        index += 1
    prefix = current[:index].rstrip()
    if not prefix:
        return ""
    boundary = max(prefix.rfind(" "), prefix.rfind("，"), prefix.rfind("。"))
    return prefix if boundary < 0 else prefix[: boundary + 1].rstrip()
