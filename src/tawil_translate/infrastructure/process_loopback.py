from __future__ import annotations

import asyncio
import os
import platform
import struct
from collections.abc import AsyncIterator
from pathlib import Path
from time import monotonic

from tawil_translate.domain.models import AudioFrame

MINIMUM_WINDOWS_BUILD = 20348
_HEADER = struct.Struct("<4sIHH")
_MAGIC = b"TWPC"


class ProcessLoopbackUnavailable(RuntimeError):
    pass


class ProcessLoopbackSource:
    """Async bridge to the native process-loopback helper's framed PCM stdout."""

    def __init__(self, *, pid: int, helper_path: Path, frame_ms: int = 20) -> None:
        if pid <= 0:
            raise ValueError("target process PID must be positive")
        self.pid = pid
        self.helper_path = helper_path
        self.frame_ms = frame_ms
        self._process: asyncio.subprocess.Process | None = None

    def validate(self) -> None:
        if os.name != "nt":
            raise ProcessLoopbackUnavailable("process loopback requires Windows")
        try:
            build = int(platform.version().split(".")[-1])
        except ValueError:
            build = 0
        if build and build < MINIMUM_WINDOWS_BUILD:
            raise ProcessLoopbackUnavailable(
                f"Windows build {MINIMUM_WINDOWS_BUILD}+ is required; current build is {build}"
            )
        if not self.helper_path.is_file():
            raise ProcessLoopbackUnavailable(
                f"native capture helper is missing: {self.helper_path}; run scripts/build_audio_helper.ps1"
            )

    async def frames(self) -> AsyncIterator[AudioFrame]:
        self.validate()
        flags = getattr(__import__("subprocess"), "CREATE_NO_WINDOW", 0)
        self._process = await asyncio.create_subprocess_exec(
            str(self.helper_path),
            "--pid",
            str(self.pid),
            "--include-tree",
            "--frame-ms",
            str(self.frame_ms),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=flags,
        )
        assert self._process.stdout is not None
        try:
            while True:
                header = await self._process.stdout.readexactly(_HEADER.size)
                magic, length, channels, sample_rate = _HEADER.unpack(header)
                if magic != _MAGIC or length > 4 * 1024 * 1024:
                    raise ProcessLoopbackUnavailable("capture helper emitted an invalid frame")
                pcm = await self._process.stdout.readexactly(length)
                yield AudioFrame(pcm, sample_rate, channels, monotonic())
        except asyncio.IncompleteReadError:
            code = await self._process.wait()
            detail = ""
            if self._process.stderr:
                detail = (await self._process.stderr.read()).decode(errors="replace").strip()
            if code:
                raise ProcessLoopbackUnavailable(detail or f"capture helper exited with code {code}")
        finally:
            await self.close()

    async def close(self) -> None:
        if self._process and self._process.returncode is None:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=2.0)
            except TimeoutError:
                self._process.kill()
                await self._process.wait()
        self._process = None
