"""Mouse control and wait actions."""
from __future__ import annotations
import time

from . import config


def act_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.click(int(x), int(y), button=button, clicks=int(clicks))
        return f"clicked ({x},{y})"
    except Exception as e:
        return f"error clicking: {e}"


def act_move_mouse(x: int, y: int, duration: float = 0.2) -> str:
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.moveTo(int(x), int(y), duration=duration)
        return f"moved to ({x},{y})"
    except Exception as e:
        return f"error moving: {e}"


def act_wait(seconds: float) -> str:
    try:
        end = time.time() + float(seconds)
        while time.time() < end:
            if config.STOP_EVENT.is_set():
                return "cancelled by user"
            time.sleep(0.1)
        return f"waited {seconds}s"
    except Exception as e:
        return f"error wait: {e}"
