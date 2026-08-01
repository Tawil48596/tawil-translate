from __future__ import annotations

import asyncio
import traceback
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tawil_translate.application.model_catalog import get_profile
from tawil_translate.application.model_manager import LocalModelManager
from tawil_translate.application.service import build_pipeline
from tawil_translate.domain.config import AppConfig
from tawil_translate.domain.models import HealthEvent, MetricEvent, SubtitleEvent
from tawil_translate.infrastructure.secrets import get_api_key
from tawil_translate.paths import model_root


class DesktopController(QObject):
    status_changed = Signal(str, str)
    running_changed = Signal(bool)
    api_models_ready = Signal(object)
    api_check_failed = Signal(str)
    model_download_finished = Signal(str)
    model_download_failed = Signal(str)
    model_download_progress = Signal(int, int, int, float, str)

    def __init__(self, config_path: Path, overlay) -> None:
        super().__init__()
        self.config_path = config_path
        self.overlay = overlay
        self._task: asyncio.Task | None = None
        self._operation: asyncio.Task | None = None
        self._active_utterance_id: str | None = None

    def check_api(self) -> None:
        self._start_operation(self._check_api())

    def download_model(self, profile_id: str) -> None:
        self._start_operation(self._download_model(profile_id))

    def _start_operation(self, coroutine) -> None:
        if self._operation and not self._operation.done():
            return
        self._operation = asyncio.create_task(coroutine)

    async def _check_api(self) -> None:
        try:
            import httpx

            config = AppConfig.load(self.config_path)
            api_key = get_api_key(config.translation.api_key_env)
            if not api_key:
                raise ValueError("请先输入并保存 API Key")
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=4.0)) as client:
                response = await client.get(
                    f"{config.translation.base_url.rstrip('/')}/models", headers=headers
                )
                response.raise_for_status()
                payload = response.json()
            models = sorted(
                item["id"] for item in payload.get("data", []) if isinstance(item, dict) and item.get("id")
            )
            if not models:
                raise RuntimeError("连接成功，但接口没有返回可用模型")
            self.api_models_ready.emit(models)
        except Exception as exc:  # noqa: BLE001 - shown as an inline UI error
            self.api_check_failed.emit(str(exc))

    async def _download_model(self, profile_id: str) -> None:
        try:
            config = AppConfig.load(self.config_path)
            profile = get_profile(profile_id)
            self.status_changed.emit("working", f"正在下载 {profile.label} 模型")
            await LocalModelManager(model_root(config.stt.model_dir)).download(
                profile,
                source=config.stt.download_source,
                progress=lambda item: self.model_download_progress.emit(
                    item.percent,
                    item.downloaded_bytes,
                    item.total_bytes,
                    item.bytes_per_second,
                    item.source_label,
                ),
            )
            self.model_download_finished.emit(profile_id)
            self.status_changed.emit("idle", "本地语音模型已就绪")
        except Exception as exc:  # noqa: BLE001 - shown as an inline UI error
            self.model_download_failed.emit(str(exc))

    def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="translation-pipeline")
        self.running_changed.emit(True)

    def stop(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def shutdown(self) -> None:
        self.stop()
        if self._task:
            with suppress(asyncio.CancelledError):
                await self._task

    async def _run(self) -> None:
        try:
            config = AppConfig.load(self.config_path)
            pipeline = build_pipeline(config, self.emit)
            await pipeline.run()
        except asyncio.CancelledError:
            self.status_changed.emit("idle", "已停止")
            raise
        except Exception as exc:  # noqa: BLE001 - user-facing task boundary
            self._write_diagnostic("pipeline startup/runtime failure", exc)
            self.status_changed.emit("error", str(exc))
        finally:
            self.running_changed.emit(False)

    async def emit(self, event: object) -> None:
        if isinstance(event, SubtitleEvent):
            if not event.translated_text and not event.is_final:
                self._active_utterance_id = event.utterance_id
            if self._active_utterance_id in {None, event.utterance_id}:
                self.overlay.set_subtitle(event.source_text, event.translated_text)
            if event.is_final:
                self.status_changed.emit("listening", f"延迟 {event.latency_ms} ms")
        elif isinstance(event, HealthEvent):
            self.overlay.set_health(event.state.value)
            self.status_changed.emit(event.state.value, event.detail or event.component)
        elif isinstance(event, MetricEvent):
            self.status_changed.emit("listening", f"{event.value:.0f} {event.unit}")

    def _write_diagnostic(self, context: str, error: Exception) -> None:
        log_path = self.config_path.parent / "app.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as output:
            output.write(f"\n[{context}] {error}\n")
            output.write("".join(traceback.format_exception(error)))
