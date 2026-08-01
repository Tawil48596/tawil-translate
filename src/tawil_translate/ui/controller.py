from __future__ import annotations

import asyncio
from contextlib import suppress
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from tawil_translate.application.service import build_pipeline
from tawil_translate.domain.config import AppConfig
from tawil_translate.domain.models import HealthEvent, MetricEvent, SubtitleEvent


class DesktopController(QObject):
    status_changed = Signal(str, str)
    running_changed = Signal(bool)

    def __init__(self, config_path: Path, overlay) -> None:
        super().__init__()
        self.config_path = config_path
        self.overlay = overlay
        self._task: asyncio.Task | None = None

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
            self.status_changed.emit("error", str(exc))
        finally:
            self.running_changed.emit(False)

    async def emit(self, event: object) -> None:
        if isinstance(event, SubtitleEvent):
            self.overlay.set_subtitle(event.source_text, event.translated_text)
            if event.is_final:
                self.status_changed.emit("listening", f"延迟 {event.latency_ms} ms")
        elif isinstance(event, HealthEvent):
            self.overlay.set_health(event.state.value)
            self.status_changed.emit(event.state.value, event.detail or event.component)
        elif isinstance(event, MetricEvent):
            self.status_changed.emit("listening", f"{event.value:.0f} {event.unit}")
