"""App launch, URL open, folder creation, window focus."""
from __future__ import annotations
import os
import subprocess
import sys
import time
from pathlib import Path

from .helpers import _devnull


def act_open_app(name: str) -> str:
    if not name:
        return "error: empty app name"
    try:
        if os.name == "nt":
            subprocess.Popen(f'start "" "{name}"', shell=True,
                             stdout=_devnull(), stderr=_devnull())
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name],
                             stdout=_devnull(), stderr=_devnull())
        else:
            subprocess.Popen([name], stdout=_devnull(), stderr=_devnull())
        time.sleep(1.5)
        return f"launched {name}"
    except Exception as e:
        return f"error launching {name}: {e}"


def act_open_url(url: str) -> str:
    if not url:
        return "error: open_url called with empty url"
    try:
        if os.name == "nt":
            os.startfile(url)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=_devnull(), stderr=_devnull())
        else:
            subprocess.Popen(["xdg-open", url], stdout=_devnull(), stderr=_devnull())
        time.sleep(1.5)
        return f"opened {url}"
    except Exception as e:
        return f"error opening {url}: {e}"


def act_create_folder(path: str) -> str:
    """Create a directory tree (parents included). Idempotent."""
    if not path:
        return "error: create_folder called with empty path"
    p = Path(os.path.expanduser(path))
    try:
        p.mkdir(parents=True, exist_ok=True)
        return f"folder ready: {p}"
    except Exception as e:
        return f"error creating folder {p}: {e}"


def act_focus_window(title_substr: str) -> str:
    try:
        import pygetwindow as gw
    except Exception as e:
        return f"error: pygetwindow not installed ({e})"
    if not title_substr:
        return "error: empty title_substr"
    wins = gw.getWindowsWithTitle(title_substr)
    if not wins:
        return f"error: no window matching {title_substr!r}"
    w = wins[0]
    try:
        if w.isMinimized:
            w.restore()
        w.activate()
        time.sleep(0.35)
        return f"focused {w.title!r}"
    except Exception as e:
        return f"error activating: {e}"
