"""File read and Notepad save-as actions."""
from __future__ import annotations
import os
import time
from pathlib import Path

from . import config


def act_read_file(path: str) -> str:
    if not path:
        return "error: read_file called with empty path"
    p = Path(path).expanduser()
    if not p.exists():
        return f"error: {p} not found"
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:4000]
    except Exception as e:
        return f"error reading: {e}"


def act_notepad_save_as(path: str) -> str:
    """Save current Notepad doc via real Save-As dialog. Auto-creates parent folder."""
    if not path:
        return "error: notepad_save_as called with empty path"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"

    target = Path(os.path.expanduser(path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"error: cannot create parent folder {target.parent}: {e}"

    for attempt in (1, 2):
        try:
            import pyautogui
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.9)
            pyautogui.write(str(target), interval=0.01)
            time.sleep(0.25)
            pyautogui.press("enter")
            time.sleep(0.7)
            pyautogui.press("enter")
            time.sleep(0.4)
        except Exception as e:
            return f"error save-as (attempt {attempt}): {e}"

        if target.exists():
            size = target.stat().st_size
            return f"saved OK -> {target} ({size} bytes)"

        try:
            import pyautogui
            pyautogui.press("esc")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.6)
        except Exception:
            pass

    return f"error: file was NOT created at {target} after 2 attempts."
