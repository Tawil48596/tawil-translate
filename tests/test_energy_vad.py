import struct

from tawil_translate.domain.models import AudioFrame
from tawil_translate.infrastructure.energy_vad import EnergyVAD


def _frame(amplitude: int, captured_at: float) -> AudioFrame:
    pcm = struct.pack("<320h", *([amplitude] * 320))
    return AudioFrame(pcm, 16_000, 1, captured_at)


async def test_energy_vad_commits_after_tail_silence() -> None:
    vad = EnergyVAD(threshold=400, silence_ms=40, min_speech_ms=20)
    assert await vad.feed(_frame(1000, 1.0)) == []
    assert await vad.feed(_frame(0, 1.02)) == []
    segments = await vad.feed(_frame(0, 1.04))
    assert len(segments) == 1
    assert segments[0].sample_rate == 16_000
