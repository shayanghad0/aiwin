"""General helpers used across modules."""
from __future__ import annotations
import os
import subprocess
import tempfile
from pathlib import Path

from . import config


def _safe_screenshot_path(path: str | None) -> str:
    if not path:
        return os.path.join(tempfile.gettempdir(), "nara_screen.png")
    p = Path(os.path.expanduser(path))
    if not p.parent.exists():
        p = Path(tempfile.gettempdir()) / p.name
    return str(p)


def _devnull():
    return subprocess.DEVNULL
