"""Screen capture, vision, and screen-size actions."""
from __future__ import annotations
import base64
import os
import tempfile

from . import config
from .helpers import _safe_screenshot_path
from .chat import _chat_with_fallback


def act_screenshot(path: str = "") -> str:
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        target = _safe_screenshot_path(path)
        pyautogui.screenshot(target)
        return f"saved {target}"
    except Exception as e:
        return f"error screenshot: {e}"


def act_look_at_screen(question: str = "") -> str:
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"

    config.BRIDGE.vision_started.emit()
    try:
        tmp = os.path.join(tempfile.gettempdir(), "nara_look.png")
        try:
            import pyautogui
            pyautogui.screenshot(tmp)
        except Exception as e:
            return f"error taking screenshot: {e}"

        try:
            with open(tmp, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except Exception as e:
            return f"error reading screenshot: {e}"

        q = question or (
            "You are looking at a Windows desktop screenshot. Describe: "
            "(a) which windows are visible, (b) the main UI elements with "
            "approximate pixel coordinates (assume 1920x1080 unless obvious "
            "otherwise), (c) anything that looks like a Play button, navigation "
            "list, search box, or error dialog. Be concise — under 200 words."
        )
        try:
            r, used = _chat_with_fallback(
                config.VISION_MODELS,
                messages=[{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": q},
                        {"type": "image_url",
                         "image_url": {"url": f"data:image/png;base64,{b64}"}},
                    ],
                }],
                max_tokens=600,
                temperature=0.1,
            )
            text = (r.choices[0].message.content or "(empty vision response)").strip()
            if used != config.VISION_MODELS[0]:
                text = f"[served by {used}] " + text
            return text
        except Exception as e:
            return f"error: all vision models failed ({e})"
    finally:
        config.BRIDGE.vision_finished.emit()


def act_get_screen_size() -> str:
    if not config.HAS_GUI:
        return f"error: GUI unavailable ({config.GUI_IMPORT_ERROR})"
    try:
        import pyautogui
        w, h = pyautogui.size()
        return f"screen size: {w}x{h}"
    except Exception as e:
        return f"error getting screen size: {e}"
