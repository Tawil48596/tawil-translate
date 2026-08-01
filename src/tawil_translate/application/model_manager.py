from __future__ import annotations

import asyncio
from pathlib import Path

from .model_catalog import STTProfile


class LocalModelManager:
    def __init__(self, model_root: Path) -> None:
        self.model_root = model_root

    def path_for(self, profile: STTProfile) -> Path:
        return self.model_root / profile.id

    def is_downloaded(self, profile: STTProfile) -> bool:
        path = self.path_for(profile)
        return (path / "model.bin").is_file() and (path / "config.json").is_file()

    async def download(self, profile: STTProfile) -> Path:
        destination = self.path_for(profile)
        destination.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._download_sync, profile, destination)
        if not self.is_downloaded(profile):
            raise RuntimeError("model download finished but required files are missing")
        return destination

    @staticmethod
    def _download_sync(profile: STTProfile, destination: Path) -> None:
        try:
            from faster_whisper.utils import download_model
        except ImportError as exc:
            raise RuntimeError("Faster-Whisper is not installed") from exc
        download_model(profile.model, output_dir=str(destination), local_files_only=False)
