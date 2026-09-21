"""Keyboard input actions: paste, type, press, hotkey."""
from __future__ import annotations
import time

from . import config


def act_paste_text(text: str) -> str:
    if not text:
        return "error: paste_text called with empty text."
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    if not config.HAS_CLIP:
        return f"error: pyperclip unavailable ({config.CLIP_IMPORT_ERROR})"
    try:
        import pyperclip, pyautogui
        pyperclip.copy(text)
        time.sleep(0.15)
        pyautogui.hotkey("ctrl", "v")
        time.sleep(0.15)
        return f"pasted {len(text)} chars"
    except Exception as e:
        return f"error pasting: {e}"


def act_type_text(text: str) -> str:
    if not text:
        return "error: type_text called with empty text"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.write(text, interval=0.01)
        return f"typed {len(text)} chars"
    except Exception as e:
        return f"error typing: {e}"


def act_press_key(key: str) -> str:
    if not key:
        return "error: press_key called with empty key"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.press(key)
        return f"pressed {key}"
    except Exception as e:
        return f"error pressing {key}: {e}"


def act_hotkey(keys: list[str]) -> str:
    if not keys or not isinstance(keys, list):
        return "error: hotkey expects a non-empty list"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.hotkey(*keys)
        return f"hotkey {'+'.join(keys)}"
    except Exception as e:
        return f"error hotkey: {e}"
