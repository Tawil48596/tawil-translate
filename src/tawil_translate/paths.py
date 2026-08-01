from __future__ import annotations

import os
import sys
from pathlib import Path


def resource_root() -> Path:
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else Path.cwd()


def default_user_config() -> Path:
    if getattr(sys, "frozen", False):
        base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TawilTranslate"
        return base / "user_config.json"
    return Path("configs/user_config.json")


def model_root(configured: str | Path) -> Path:
    path = Path(configured).expanduser()
    if path.is_absolute():
        return path
    # Portable builds keep downloaded models beside the executable, never in
    # Explorer's or the shell's unpredictable current working directory.
    base = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    return (base / path).resolve()
