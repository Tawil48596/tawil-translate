from __future__ import annotations

import asyncio
import ctypes
import io
import os
import sys
import wave
from collections import Counter, deque
from functools import partial
from uuid import uuid4

from tawil_translate.application.model_catalog import STTProfile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.domain.models import SpeechSegment, Transcript
from tawil_translate.paths import model_root

_DLL_DIRECTORY_HANDLES: list[object] = []


class FasterWhisperSTT:
    """Lazy-loaded adapter; inference runs off the asyncio/Qt main thread."""

    def __init__(self, profile: STTProfile, model_dir: str, language: str | None = None) -> None:
        self.profile = profile
        self.model_dir = model_dir
        self.language = language
        self._detected_language: str | None = language
        self._language_votes: deque[str] = deque(maxlen=3)
        self._model = None
        self._lock = asyncio.Lock()
        self._inference_lock = asyncio.Lock()

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
        if self.profile.device == "cuda" and not _cuda_runtime_available():
            raise RuntimeError(
                "GPU STT requires bundled CUDA 12 cuBLAS/cuDNN; the runtime self-check failed"
            )
        self._model = WhisperModel(
            str(model_path),
            device=self.profile.device,
            compute_type=self.profile.compute_type,
            local_files_only=True,
        )
        if self.profile.device == "cuda":
            # Force the first CUDA kernels to run during warmup, not on the
            # first live subtitle where they would cause a visible stall.
            audio = _pcm16_wav(bytes(16_000), 16_000)
            segments, _ = self._model.transcribe(
                audio, language="en", beam_size=1, vad_filter=False
            )
            list(segments)

    async def transcribe(self, segment: SpeechSegment) -> Transcript:
        await self.warmup()
        async with self._inference_lock:
            return await asyncio.to_thread(partial(self._transcribe_sync, segment))

    def _transcribe_sync(self, segment: SpeechSegment) -> Transcript:
        audio = _pcm16_wav(segment.audio, segment.sample_rate)
        # A small beam is the best latency/quality tradeoff for live captions.
        beam_size = 1 if not segment.committed else {"balanced": 3, "accurate": 5}.get(
            self.profile.id, 1
        )
        segments, info = self._model.transcribe(
            audio,
            language=self._detected_language,
            beam_size=beam_size,
            patience=1.0,
            initial_prompt=None,
            condition_on_previous_text=False,
            vad_filter=False,
            without_timestamps=True,
            temperature=0.0,
            repetition_penalty=1.05,
            no_repeat_ngram_size=3,
        )
        text = "".join(item.text for item in segments).strip()
        detected = getattr(info, "language", None)
        probability = getattr(info, "language_probability", 0.0)
        if self.language is None and detected and probability >= 0.80:
            self._language_votes.append(detected)
            winner, count = Counter(self._language_votes).most_common(1)[0]
            # Do not permanently lock from one noisy game/music chunk. A later
            # unanimous window can also recover after the programme changes.
            if count >= 3:
                self._detected_language = winner
        return Transcript(uuid4().hex, text, detected, committed=True)

    async def close(self) -> None:
        self._model = None
        self._detected_language = self.language
        self._language_votes.clear()


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
    _add_bundled_cuda_directories()
    for library in ("cublas64_12.dll", "cudnn64_9.dll"):
        try:
            ctypes.WinDLL(library)
        except OSError:
            return False
    return True


def _add_bundled_cuda_directories() -> None:
    if not hasattr(os, "add_dll_directory"):
        return
    root = getattr(sys, "_MEIPASS", None)
    if not root:
        return
    for relative in (("nvidia", "cublas", "bin"), ("nvidia", "cudnn", "bin")):
        directory = os.path.join(root, *relative)
        if os.path.isdir(directory):
            _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(directory))
