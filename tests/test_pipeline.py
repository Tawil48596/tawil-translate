import asyncio
from collections.abc import AsyncIterator

from tawil_translate.application.pipeline import TranslationPipeline
from tawil_translate.domain.models import AudioFrame, SpeechSegment, SubtitleEvent, Transcript
from tawil_translate.infrastructure.demo import DemoAudioSource, DemoSTT, DemoTranslator, DemoVAD


async def test_pipeline_emits_two_locked_subtitles() -> None:
    events: list[object] = []

    async def emit(event: object) -> None:
        events.append(event)

    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=DemoSTT(),
        translator=DemoTranslator(),
        emit=emit,
        queue_size=1,
    )
    await pipeline.run()
    captions = [event for event in events if isinstance(event, SubtitleEvent)]
    finals = [event for event in events if isinstance(event, SubtitleEvent) and event.is_final]
    assert [event.translated_text for event in finals] == ["欢迎来到竞技场", "目标正在遭受攻击"]
    assert len({event.utterance_id for event in finals}) == 2
    assert [
        event.source_text
        for event in captions
        if not event.is_final and not event.translated_text
    ] == [
        "Welcome to the arena",
        "The objective is under attack",
    ]
    assert all(event.translated_text for event in finals)


async def test_pipeline_emits_source_captions_when_translation_is_disabled() -> None:
    events: list[object] = []

    async def emit(event: object) -> None:
        events.append(event)

    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=DemoSTT(),
        translator=None,
        emit=emit,
        queue_size=1,
        translation_enabled=False,
    )
    await pipeline.run()

    captions = [event for event in events if isinstance(event, SubtitleEvent)]
    finals = [event for event in captions if event.is_final]
    assert len(finals) == 2
    assert all(event.source_text for event in finals)
    assert all(event.translated_text == "" for event in captions)


async def test_slow_translation_does_not_block_following_transcription() -> None:
    events: list[object] = []
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    class TrackingSTT(DemoSTT):
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def transcribe(self, segment: SpeechSegment) -> Transcript:
            text = segment.audio.decode()
            self.calls.append(text)
            return Transcript(text, text, "en")

    class OrderedTranslator:
        async def translate(
            self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
        ) -> AsyncIterator[str]:
            if text == "Welcome to the arena":
                await release_first.wait()
            else:
                second_started.set()
            yield f"translated:{text}"

    async def emit(event: object) -> None:
        events.append(event)

    stt = TrackingSTT()
    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=stt,
        translator=OrderedTranslator(),
        emit=emit,
        queue_size=2,
    )
    task = asyncio.create_task(pipeline.run())
    await asyncio.sleep(0.15)
    assert stt.calls == ["Welcome to the arena", "The objective is under attack"]
    assert second_started.is_set()
    early_finals = [
        event for event in events if isinstance(event, SubtitleEvent) and event.is_final
    ]
    assert [event.source_text for event in early_finals] == [
        "The objective is under attack"
    ]
    release_first.set()
    await task

    finals = [event for event in events if isinstance(event, SubtitleEvent) and event.is_final]
    assert [event.source_text for event in finals] == [
        "The objective is under attack",
        "Welcome to the arena",
    ]


async def test_translation_failure_falls_back_to_complete_source_caption() -> None:
    events: list[object] = []

    class FailingTranslator:
        async def translate(
            self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
        ) -> AsyncIterator[str]:
            raise RuntimeError("network unavailable")
            yield  # pragma: no cover - keeps this an async generator

    async def emit(event: object) -> None:
        events.append(event)

    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=DemoSTT(),
        translator=FailingTranslator(),
        emit=emit,
        queue_size=2,
    )
    await pipeline.run()

    finals = [event for event in events if isinstance(event, SubtitleEvent) and event.is_final]
    assert [event.source_text for event in finals] == [
        "Welcome to the arena",
        "The objective is under attack",
    ]
    assert all(event.translated_text == "" for event in finals)


async def test_translation_first_token_timeout_falls_back_without_stalling() -> None:
    events: list[object] = []

    class HangingTranslator:
        async def translate(
            self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
        ) -> AsyncIterator[str]:
            await asyncio.sleep(1)
            yield "too late"

    async def emit(event: object) -> None:
        events.append(event)

    pipeline = TranslationPipeline(
        audio=DemoAudioSource(),
        vad=DemoVAD(),
        stt=DemoSTT(),
        translator=HangingTranslator(),
        emit=emit,
        queue_size=2,
        first_token_timeout=0.05,
        translation_timeout=0.1,
    )
    await asyncio.wait_for(pipeline.run(), timeout=0.5)

    finals = [event for event in events if isinstance(event, SubtitleEvent) and event.is_final]
    assert len(finals) == 2
    assert all(event.translated_text == "" for event in finals)


async def test_preview_caption_is_replaced_by_committed_caption() -> None:
    events: list[object] = []
    translation_calls: list[str] = []

    class PreviewAudio:
        async def frames(self):
            yield AudioFrame(b"preview", 16_000, 1, 1.0)
            await asyncio.sleep(0.01)
            yield AudioFrame(b"final", 16_000, 1, 2.0)

    class PreviewVAD:
        async def warmup(self) -> None:
            return None

        async def feed(self, frame: AudioFrame) -> list[SpeechSegment]:
            return [
                SpeechSegment(
                    frame.pcm,
                    16_000,
                    1.0,
                    frame.captured_at,
                    committed=frame.pcm == b"final",
                )
            ]

        async def flush(self) -> list[SpeechSegment]:
            return []

    class PreviewSTT(DemoSTT):
        async def transcribe(self, segment: SpeechSegment) -> Transcript:
            text = "hello world"
            return Transcript("caption", text, "en", committed=segment.committed)

    class PreviewTranslator:
        async def translate(
            self, text: str, *, context: tuple[str, ...], glossary: dict[str, str]
        ) -> AsyncIterator[str]:
            translation_calls.append(text)
            yield "你好，世界"

    async def emit(event: object) -> None:
        events.append(event)

    pipeline = TranslationPipeline(
        audio=PreviewAudio(),
        vad=PreviewVAD(),
        stt=PreviewSTT(),
        translator=PreviewTranslator(),
        emit=emit,
    )
    await pipeline.run()

    captions = [event for event in events if isinstance(event, SubtitleEvent)]
    assert any(
        event.utterance_id == "preview" and event.translated_text == "你好，世界"
        for event in captions
    )
    assert captions[-1].source_text == "hello world"
    assert captions[-1].translated_text == "你好，世界"
    assert captions[-1].is_final
    assert translation_calls == ["hello world"]
