from __future__ import annotations

from dataclasses import dataclass, field
from math import isqrt

from tawil_translate.domain.models import AudioFrame, SpeechSegment


@dataclass(slots=True)
class EnergyVAD:
    """Zero-download fallback VAD; Silero can replace it through the same port."""

    threshold: int = 420
    silence_ms: int = 280
    min_speech_ms: int = 180
    _frames: list[AudioFrame] = field(default_factory=list)
    _silent_ms: int = 0

    async def warmup(self) -> None:
        return None

    async def feed(self, frame: AudioFrame) -> list[SpeechSegment]:
        duration_ms = max(1, round(len(frame.pcm) / 2 / frame.sample_rate * 1000))
        samples = memoryview(frame.pcm).cast("h")
        rms = isqrt(sum(sample * sample for sample in samples) // max(1, len(samples)))
        voiced = rms >= self.threshold
        if voiced:
            self._frames.append(frame)
            self._silent_ms = 0
            return []
        if not self._frames:
            return []
        self._silent_ms += duration_ms
        if self._silent_ms < self.silence_ms:
            self._frames.append(frame)
            return []
        return self._flush_if_valid()

    async def flush(self) -> list[SpeechSegment]:
        return self._flush_if_valid()

    def _flush_if_valid(self) -> list[SpeechSegment]:
        frames, self._frames = self._frames, []
        self._silent_ms = 0
        if not frames:
            return []
        duration_ms = sum(len(item.pcm) / 2 / item.sample_rate * 1000 for item in frames)
        if duration_ms < self.min_speech_ms:
            return []
        start = frames[0].captured_at
        end = frames[-1].captured_at + len(frames[-1].pcm) / 2 / frames[-1].sample_rate
        return [SpeechSegment(b"".join(item.pcm for item in frames), frames[0].sample_rate, start, end)]
