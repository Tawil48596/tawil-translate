from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from .model_catalog import STTProfile

DOWNLOAD_ENDPOINTS = {
    "official": ("Hugging Face 官方", "https://huggingface.co"),
    "mirror": ("大陆加速镜像", "https://hf-mirror.com"),
}

MODEL_REPOSITORIES = {
    "tiny": "Systran/faster-whisper-tiny",
    "base": "Systran/faster-whisper-base",
    "small": "Systran/faster-whisper-small",
    "medium": "Systran/faster-whisper-medium",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    downloaded_bytes: int
    total_bytes: int
    bytes_per_second: float
    source_label: str

    @property
    def percent(self) -> int:
        if not self.total_bytes:
            return 0
        return min(99, round(self.downloaded_bytes / self.total_bytes * 100))


class LocalModelManager:
    def __init__(self, model_root: Path) -> None:
        self.model_root = model_root

    def path_for(self, profile: STTProfile) -> Path:
        return self.model_root / profile.id

    def is_downloaded(self, profile: STTProfile) -> bool:
        path = self.path_for(profile)
        return (path / "model.bin").is_file() and (path / "config.json").is_file()

    async def download(
        self,
        profile: STTProfile,
        *,
        source: str = "auto",
        progress: Callable[[DownloadProgress], None] | None = None,
    ) -> Path:
        destination = self.path_for(profile)
        destination.mkdir(parents=True, exist_ok=True)
        endpoints = [source] if source != "auto" else ["mirror", "official"]
        last_error: Exception | None = None
        for endpoint_id in endpoints:
            try:
                await self._download_with_progress(
                    profile, destination, endpoint_id, progress
                )
                break
            except Exception as exc:  # noqa: BLE001 - retry another configured endpoint
                last_error = exc
        else:
            raise RuntimeError(f"all model download sources failed: {last_error}") from last_error
        if not self.is_downloaded(profile):
            raise RuntimeError("model download finished but required files are missing")
        return destination

    async def _download_with_progress(
        self,
        profile: STTProfile,
        destination: Path,
        endpoint_id: str,
        progress: Callable[[DownloadProgress], None] | None,
    ) -> None:
        label, endpoint = DOWNLOAD_ENDPOINTS[endpoint_id]
        total = round(profile.approximate_download_gb * 1024**3)
        initial = self._directory_size(destination)
        started = monotonic()
        task = asyncio.create_task(
            asyncio.to_thread(self._download_sync, profile, destination, endpoint)
        )
        while not task.done():
            downloaded = self._directory_size(destination)
            elapsed = max(monotonic() - started, 0.1)
            if progress:
                progress(DownloadProgress(downloaded, total, max(0, downloaded - initial) / elapsed, label))
            await asyncio.sleep(0.5)
        await task
        if progress:
            progress(DownloadProgress(total, total, 0, label))

    @staticmethod
    def _directory_size(path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    @staticmethod
    def _download_sync(profile: STTProfile, destination: Path, endpoint: str) -> None:
        try:
            from huggingface_hub import snapshot_download
        except ImportError as exc:
            raise RuntimeError("Faster-Whisper is not installed") from exc
        repository = MODEL_REPOSITORIES.get(profile.model, profile.model)
        snapshot_download(
            repo_id=repository,
            local_dir=str(destination),
            endpoint=endpoint,
        )
