from __future__ import annotations

import subprocess


def detect_cuda_vram_gb() -> float | None:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
            check=True,
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=flags,
        )
    except (FileNotFoundError, subprocess.SubprocessError):
        return None
    values = [float(line.strip()) / 1024 for line in result.stdout.splitlines() if line.strip()]
    return max(values) if values else None
