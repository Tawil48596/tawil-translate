from __future__ import annotations

import asyncio
import io
import wave
from functools import partial
from pathlib import Path
from uuid import uuid4

from tawil_translate.application.model_catalog import STTProfile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.domain.models import SpeechSegment, Transcript


class FasterWhisperSTT:
    """Lazy-loaded adapter; inference runs off the asyncio/Qt main thread."""

    def __init__(self, profile: STTProfile, model_dir: str, language: str | None = None) -> None:
        self.profile = profile
        self.model_dir = model_dir
        self.language = language
        self._model = None
        self._lock = asyncio.Lock()

    async def warmup(self) -> None:
        if self._model is not None:
            return
        async with self._lock:
            if self._model is None:
                await asyncio.to_thread(self._load)

    def _load(self) -> None:
        try:
            from faster_whisper import WhisperModel
        except ImportError as exc:
            raise RuntimeError('install desktop dependencies: pip install -e ".[desktop]"') from exc
        model_path = LocalModelManager(Path(self.model_dir)).path_for(self.profile)
        if not LocalModelManager(Path(self.model_dir)).is_downloaded(self.profile):
            raise RuntimeError("selected STT model is not downloaded; download it in Settings first")
        self._model = WhisperModel(
            str(model_path),
            device=self.profile.device,
            compute_type=self.profile.compute_type,
            local_files_only=True,
        )

    async def transcribe(self, segment: SpeechSegment) -> Transcript:
        await self.warmup()
        return await asyncio.to_thread(partial(self._transcribe_sync, segment))

    def _transcribe_sync(self, segment: SpeechSegment) -> Transcript:
        audio = _pcm16_wav(segment.audio, segment.sample_rate)
        segments, info = self._model.transcribe(
            audio,
            language=self.language,
            beam_size=1,
            best_of=1,
            condition_on_previous_text=False,
            vad_filter=False,
        )
        text = "".join(item.text for item in segments).strip()
        return Transcript(uuid4().hex, text, getattr(info, "language", None), committed=True)

    async def close(self) -> None:
        self._model = None


def _pcm16_wav(pcm: bytes, sample_rate: int) -> io.BytesIO:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    output.seek(0)
    return output
