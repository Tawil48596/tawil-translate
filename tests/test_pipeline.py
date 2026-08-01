from tawil_translate.application.pipeline import TranslationPipeline
from tawil_translate.domain.models import SubtitleEvent
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
    finals = [event for event in events if isinstance(event, SubtitleEvent) and event.is_final]
    assert [event.translated_text for event in finals] == ["欢迎来到竞技场", "目标正在遭受攻击"]
    assert len({event.utterance_id for event in finals}) == 2

