from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from tawil_translate.domain.models import AudioFrame, SpeechSegment


@dataclass(slots=True)
class SileroVAD:
    """Streaming Silero ONNX VAD with 32ms inference windows and bounded state."""

    threshold: float = 0.5
    silence_ms: int = 280
    min_speech_ms: int = 180
    sample_rate: int = 16_000
    _model: object | None = None
    _input: bytearray = field(default_factory=bytearray)
    _speech: bytearray = field(default_factory=bytearray)
    _active: bool = False
    _silent_ms: int = 0
    _started_at: float = 0.0
    _last_at: float = 0.0

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
                self._speech.extend(window)
                self._silent_ms = 0
            elif self._active:
                self._speech.extend(window)
                self._silent_ms += duration_ms
                if self._silent_ms >= self.silence_ms:
                    output.extend(self._finish())
        return output

    def _probability(self, pcm: bytes) -> float:
        import torch

        samples = torch.frombuffer(bytearray(pcm), dtype=torch.int16).to(torch.float32) / 32768.0
        return float(self._model(samples, self.sample_rate).item())

    async def flush(self) -> list[SpeechSegment]:
        if self._active and self._input:
            self._speech.extend(self._input)
        self._input.clear()
        return self._finish()

    def _finish(self) -> list[SpeechSegment]:
        duration_ms = len(self._speech) / 2 / self.sample_rate * 1000
        audio = bytes(self._speech)
        self._speech.clear()
        self._active = False
        self._silent_ms = 0
        if duration_ms < self.min_speech_ms:
            return []
        return [SpeechSegment(audio, self.sample_rate, self._started_at, self._last_at)]
