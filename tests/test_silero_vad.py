import struct

from tawil_translate.domain.models import AudioFrame
from tawil_translate.infrastructure.silero_vad import SileroVAD


def _frame(amplitude: int, captured_at: float) -> AudioFrame:
    pcm = struct.pack("<320h", *([amplitude] * 320))
    return AudioFrame(pcm, 16_000, 1, captured_at)


async def test_loud_non_speech_is_not_forced_into_whisper(monkeypatch) -> None:
    vad = SileroVAD(max_speech_ms=100)
    vad._model = object()
    monkeypatch.setattr(SileroVAD, "_probability", lambda self, pcm: 0.0)

    segments = []
    for index in range(10):
        segments.extend(await vad.feed(_frame(12_000, 1.0 + index * 0.02)))

    assert segments == []


async def test_speech_keeps_preroll_and_commits_after_silence(monkeypatch) -> None:
    probabilities = iter([0.0, 0.0, 0.9, 0.9, 0.0, 0.0])
    vad = SileroVAD(silence_ms=64, min_speech_ms=20)
    vad._model = object()
    monkeypatch.setattr(SileroVAD, "_probability", lambda self, pcm: next(probabilities))

    segments = []
    for index in range(10):
        segments.extend(await vad.feed(_frame(1_000, 1.0 + index * 0.02)))
        if segments:
            break

    assert len(segments) == 1
    assert len(segments[0].audio) >= 6 * 512 * 2


async def test_active_speech_emits_preview_without_consuming_final_audio(monkeypatch) -> None:
    vad = SileroVAD(
        silence_ms=64,
        min_speech_ms=20,
        preview_min_speech_ms=32,
        preview_interval_ms=64,
    )
    vad._model = object()
    monkeypatch.setattr(SileroVAD, "_probability", lambda self, pcm: 0.9)

    segments = []
    for index in range(8):
        segments.extend(await vad.feed(_frame(1_000, 1.0 + index * 0.02)))

    previews = [segment for segment in segments if not segment.committed]
    final = await vad.flush()
    assert previews
    assert final[0].committed
    assert len(final[0].audio) >= len(previews[-1].audio)
