"""Keyboard input actions: paste, type, press, hotkey."""
from __future__ import annotations
import time

from . import config


def act_paste_text(text: str) -> str:
    if not text:
        return ("error: paste_text called with empty text. "
                "Provide the full content under the 'text' field.")
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


def act_stream_text(text: str, interval: float = 0.035) -> str:
    """Stream text chatbot-style: word bursts with slight pauses. Aborts on ESC x5."""
    if not text:
        return "error: stream_text called with empty text"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import random
        import re
        import pyautogui
        from . import control

        base = max(float(interval), 0.005)
        words = re.findall(r"\S+\s*", text)
        typed = 0
        i = 0
        while i < len(words):
            if control.is_aborted():
                return f"aborted by user after {typed}/{len(text)} chars"
            burst = random.randint(8, 16)
            chunk = "".join(words[i:i + burst])
            i += burst
            pyautogui.write(chunk, interval=0)
            typed += len(chunk)
            if re.search(r"[.!?]\s*$", chunk):
                delay = base * random.uniform(2, 4)
            elif chunk.endswith((", ", "; ", ": ")):
                delay = base * random.uniform(1, 2)
            else:
                delay = base * random.uniform(0.2, 0.6)
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if control.is_aborted():
                    return f"aborted by user after {typed}/{len(text)} chars"
                time.sleep(0.05)
        return f"streamed {len(text)} chars (chat mode, interval={interval}s)"
    except Exception as e:
        return f"error streaming text: {e}"


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
        return "error: hotkey expects a non-empty list, e.g. ['ctrl','s']"
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        pyautogui.hotkey(*keys)
        return f"hotkey {'+'.join(keys)}"
    except Exception as e:
        return f"error hotkey: {e}"
