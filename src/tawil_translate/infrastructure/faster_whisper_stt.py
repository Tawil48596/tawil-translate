from __future__ import annotations

import asyncio
import ctypes
import io
import os
import wave
from functools import partial
from uuid import uuid4

from tawil_translate.application.model_catalog import STTProfile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.domain.models import SpeechSegment, Transcript
from tawil_translate.paths import model_root


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
        manager = LocalModelManager(model_root(self.model_dir))
        model_path = manager.path_for(self.profile)
        if not manager.is_downloaded(self.profile):
            raise RuntimeError("selected STT model is not downloaded; download it in Settings first")
        use_cuda = self.profile.device == "cuda" and _cuda_runtime_available()
        try:
            self._model = WhisperModel(
                str(model_path),
                device="cuda" if use_cuda else "cpu",
                compute_type=self.profile.compute_type if use_cuda else "int8",
                local_files_only=True,
            )
        except Exception:
            if not use_cuda:
                raise
            # Portable builds cannot assume that CUDA and cuDNN runtime DLLs
            # are installed system-wide. Keep captions functional on CPU.
            self._model = WhisperModel(
                str(model_path),
                device="cpu",
                compute_type="int8",
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


def _cuda_runtime_available() -> bool:
    if os.name != "nt":
        return True
    for library in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(library)
        except OSError:
            return False
    return True
