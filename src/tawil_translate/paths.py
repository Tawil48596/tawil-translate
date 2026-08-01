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
