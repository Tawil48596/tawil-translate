from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from math import isqrt

from tawil_translate.domain.models import AudioFrame, SpeechSegment

from .energy_vad import EnergyVAD


@dataclass(slots=True)
class SileroVAD:
    """Streaming Silero ONNX VAD with 32ms inference windows and bounded state."""

    threshold: float = 0.5
    silence_ms: int = 280
    min_speech_ms: int = 180
    sample_rate: int = 16_000
    max_speech_ms: int = 4_000
    _model: object | None = None
    _input: bytearray = field(default_factory=bytearray)
    _speech: bytearray = field(default_factory=bytearray)
    _active: bool = False
    _silent_ms: int = 0
    _started_at: float = 0.0
    _last_at: float = 0.0
    _fallback: EnergyVAD = field(default_factory=EnergyVAD)
    _raw_frames: list[AudioFrame] = field(default_factory=list)
    _raw_voiced: bool = False

    def __post_init__(self) -> None:
        self._fallback.silence_ms = self.silence_ms
        self._fallback.min_speech_ms = self.min_speech_ms
        self._fallback.max_speech_ms = self.max_speech_ms

    async def warmup(self) -> None:
        if self._model is not None:
            return
        await asyncio.to_thread(self._load)

    def _load(self) -> None:
        try:
            from silero_vad import load_silero_vad
        except ImportError as exc:
            raise RuntimeError('Silero VAD is missing; install with: pip install -e ".[desktop]"') from exc
        self._model = load_silero_vad(onnx=True, opset_version=16)

    async def feed(self, frame: AudioFrame) -> list[SpeechSegment]:
        if frame.sample_rate != self.sample_rate or frame.channels != 1:
            raise ValueError("Silero VAD requires mono 16 kHz PCM")
        await self.warmup()
        self._raw_frames.append(frame)
        samples = memoryview(frame.pcm).cast("h")
        rms = isqrt(sum(sample * sample for sample in samples) // max(1, len(samples)))
        self._raw_voiced = self._raw_voiced or rms >= self._fallback.threshold
        fallback_output = await self._fallback.feed(frame)
        self._input.extend(frame.pcm)
        self._last_at = frame.captured_at
        output: list[SpeechSegment] = []
        window_bytes = 512 * 2
        while len(self._input) >= window_bytes:
            window = bytes(self._input[:window_bytes])
            del self._input[:window_bytes]
            probability = await asyncio.to_thread(self._probability, window)
            duration_ms = 32
            if probability >= self.threshold:
                if not self._active:
                    self._active = True
                    self._started_at = frame.captured_at
                    self._fallback.reset()
                self._speech.extend(window)
                self._silent_ms = 0
                if len(self._speech) / 2 / self.sample_rate * 1000 >= self.max_speech_ms:
                    output.extend(self._finish())
            elif self._active:
                self._speech.extend(window)
                self._silent_ms += duration_ms
                if self._silent_ms >= self.silence_ms:
                    output.extend(self._finish())
        committed = output or (fallback_output if not self._active else [])
        if committed:
            self._reset_raw()
            return committed
        raw_duration_ms = sum(
            len(item.pcm) / 2 / item.sample_rate * 1000 for item in self._raw_frames
        )
        if raw_duration_ms >= self.max_speech_ms:
            return self._commit_raw()
        return []

    def _probability(self, pcm: bytes) -> float:
        import torch

        samples = torch.frombuffer(bytearray(pcm), dtype=torch.int16).to(torch.float32) / 32768.0
        return float(self._model(samples, self.sample_rate).item())

    async def flush(self) -> list[SpeechSegment]:
        if self._active and self._input:
            self._speech.extend(self._input)
        self._input.clear()
        output = self._finish()
        return output or await self._fallback.flush()

    def _finish(self) -> list[SpeechSegment]:
        duration_ms = len(self._speech) / 2 / self.sample_rate * 1000
        audio = bytes(self._speech)
        self._speech.clear()
        self._active = False
        self._silent_ms = 0
        if duration_ms < self.min_speech_ms:
            return []
        return [SpeechSegment(audio, self.sample_rate, self._started_at, self._last_at)]

    def _commit_raw(self) -> list[SpeechSegment]:
        frames = self._raw_frames
        voiced = self._raw_voiced
        self._reset_raw()
        self._input.clear()
        self._speech.clear()
        self._active = False
        self._silent_ms = 0
        self._fallback.reset()
        if not frames or not voiced:
            return []
        end = frames[-1].captured_at + len(frames[-1].pcm) / 2 / frames[-1].sample_rate
        return [
            SpeechSegment(
                b"".join(item.pcm for item in frames),
                frames[0].sample_rate,
                frames[0].captured_at,
                end,
            )
        ]

    def _reset_raw(self) -> None:
        self._raw_frames.clear()
        self._raw_voiced = False
