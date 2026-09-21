#!/usr/bin/env python3
"""
NaraRouter computer-control agent — PyQt5 GUI edition (status-bar fixed).

Layout:
  ┌──────────────────────────────┬───────────────────────────────┐
  │  LIVE DESKTOP PREVIEW        │  task input + Run/Stop        │
  │  (what the AI sees)          │  ───────────────────────────  │
  │                              │  agent log                    │
  └──────────────────────────────┴───────────────────────────────┘
"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

from PyQt5.QtCore import Qt, QThread, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QLineEdit, QPushButton, QGroupBox, QSplitter,
    QStatusBar, QSizePolicy, QMessageBox
)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
load_dotenv()

API_KEY       = os.getenv("NARA_API_KEY", "").strip()
BASE_URL      = os.getenv("NARA_BASE_URL", "https://router.bynara.id/v1").strip()
MODELS        = [m.strip() for m in os.getenv(
    "NARA_MODEL", "nemotron-3-super-free,agnes-2.5-flash"
).split(",") if m.strip()]
VISION_MODELS = [m.strip() for m in os.getenv(
    "NARA_VISION_MODEL", "nex-n2.5-pro,agnes-2.5-flash"
).split(",") if m.strip()]
MAX_STEPS     = int(os.getenv("NARA_MAX_STEPS", "20"))
CONFIRM       = os.getenv("NARA_CONFIRM", "1") not in ("0", "false", "no")

if not API_KEY or not API_KEY.startswith("sk-nry-"):
    CONFIG_ERROR = "NARA_API_KEY missing/malformed (sk-nry-...). Put it in .env"
else:
    CONFIG_ERROR = ""

client = OpenAI(base_url=BASE_URL, api_key=API_KEY) if not CONFIG_ERROR else None

try:
    import pyautogui
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.05
    HAS_GUI = True
except Exception as e:
    HAS_GUI = False
    GUI_IMPORT_ERROR = str(e)

try:
    import pyperclip
    HAS_CLIP = True
except Exception as e:
    HAS_CLIP = False
    CLIP_IMPORT_ERROR = str(e)


# ------------------------------------------------------------------
# Bridge: worker thread → main thread signals
# ------------------------------------------------------------------
class AgentBridge(QObject):
    log_line        = pyqtSignal(str)
    vision_started  = pyqtSignal()
    vision_finished = pyqtSignal()
    step_started    = pyqtSignal(int, int)
    task_done       = pyqtSignal(str)
    task_crashed    = pyqtSignal(str)


BRIDGE = AgentBridge()
STOP_EVENT = threading.Event()


def log(msg: str) -> None:
    BRIDGE.log_line.emit(str(msg))


# ------------------------------------------------------------------
# Fallback chat helper
# ------------------------------------------------------------------
def _chat_with_fallback(models: list[str], **kwargs):
    last_err: Exception | None = None
    for m in models:
        try:
            resp = client.chat.completions.create(model=m, **kwargs)
            return resp, m
        except Exception as e:
            last_err = e
            log(f"    ! model {m!r} failed: {e}")
    assert last_err is not None
    raise last_err


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------
def _safe_screenshot_path(path: str | None) -> str:
    if not path:
        return os.path.join(tempfile.gettempdir(), "nara_screen.png")
    p = Path(os.path.expanduser(path))
    if not p.parent.exists():
        p = Path(tempfile.gettempdir()) / p.name
    return str(p)


def _devnull():
    return subprocess.DEVNULL


# ------------------------------------------------------------------
# Actions
# ------------------------------------------------------------------
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


def act_paste_text(text: str) -> str:
    if not text:
        return "error: paste_text called with empty text."
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    if not HAS_CLIP:
        return f"error: pyperclip unavailable ({CLIP_IMPORT_ERROR})"
    try:
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
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.write(text, interval=0.01)
        return f"typed {len(text)} chars"
    except Exception as e:
        return f"error typing: {e}"


def act_press_key(key: str) -> str:
    if not key:
        return "error: press_key called with empty key"
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.press(key)
        return f"pressed {key}"
    except Exception as e:
        return f"error pressing {key}: {e}"


def act_hotkey(keys: list[str]) -> str:
    if not keys or not isinstance(keys, list):
        return "error: hotkey expects a non-empty list"
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.hotkey(*keys)
        return f"hotkey {'+'.join(keys)}"
    except Exception as e:
        return f"error hotkey: {e}"


def act_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.click(int(x), int(y), button=button, clicks=int(clicks))
        return f"clicked ({x},{y})"
    except Exception as e:
        return f"error clicking: {e}"


def act_move_mouse(x: int, y: int, duration: float = 0.2) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.moveTo(int(x), int(y), duration=duration)
        return f"moved to ({x},{y})"
    except Exception as e:
        return f"error moving: {e}"


def act_wait(seconds: float) -> str:
    try:
        end = time.time() + float(seconds)
        while time.time() < end:
            if STOP_EVENT.is_set():
                return "cancelled by user"
            time.sleep(0.1)
        return f"waited {seconds}s"
    except Exception as e:
        return f"error wait: {e}"


def act_screenshot(path: str = "") -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        target = _safe_screenshot_path(path)
        pyautogui.screenshot(target)
        return f"saved {target}"
    except Exception as e:
        return f"error screenshot: {e}"


def act_look_at_screen(question: str = "") -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"

    BRIDGE.vision_started.emit()
    try:
        tmp = os.path.join(tempfile.gettempdir(), "nara_look.png")
        try:
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
                VISION_MODELS,
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
            if used != VISION_MODELS[0]:
                text = f"[served by {used}] " + text
            return text
        except Exception as e:
            return f"error: all vision models failed ({e})"
    finally:
        BRIDGE.vision_finished.emit()


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


def act_get_screen_size() -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    w, h = pyautogui.size()
    return f"screen size: {w}x{h}"


def act_notepad_save_as(path: str) -> str:
    if not path:
        return "error: notepad_save_as called with empty path"
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"

    target = Path(os.path.expanduser(path))
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"error: cannot create parent folder {target.parent}: {e}"

    for attempt in (1, 2):
        try:
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
            pyautogui.press("esc")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.6)
        except Exception:
            pass

    return (f"error: file was NOT created at {target} after 2 attempts.")


def act_run_shell(command: str) -> str:
    if not command:
        return "error: run_shell called with empty command"
    if CONFIRM:
        result_holder = {"ok": False}
        done = threading.Event()

        def ask():
            r = QMessageBox.question(
                None, "Confirm shell command",
                f"Run this shell command?\n\n{command}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            result_holder["ok"] = (r == QMessageBox.Yes)
            done.set()

        QTimer.singleShot(0, ask)
        done.wait(120)
        if not result_holder["ok"]:
            return "cancelled by user"
    try:
        out = subprocess.run(command, shell=True, capture_output=True,
                             text=True, timeout=60)
        return (out.stdout or "") + (out.stderr or "") or f"exit {out.returncode}"
    except Exception as e:
        return f"error: {e}"


# ------------------------------------------------------------------
# Tool schema
# ------------------------------------------------------------------
TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Launch an application by name (e.g. 'notepad', 'FL64.exe', 'spotify').",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "open_url",
        "description": "Open a URL or app deep-link (spotify:collection, https://...).",
        "parameters": {"type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "create_folder",
        "description": "Create a folder (and any missing parents). Call BEFORE saving into a new path.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "Bring a window whose title contains this substring to the front.",
        "parameters": {"type": "object",
            "properties": {"title_substr": {"type": "string"}},
            "required": ["title_substr"]}}},
    {"type": "function", "function": {
        "name": "look_at_screen",
        "description": "Screenshot -> text description via a vision model. USE BEFORE any coordinate click.",
        "parameters": {"type": "object",
            "properties": {"question": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "paste_text",
        "description": "Paste text via clipboard. ALWAYS include non-empty 'text'.",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "Type short ASCII text at current focus.",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "press_key",
        "description": "Press ONE key. For combos use hotkey.",
        "parameters": {"type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "hotkey",
        "description": "Press a chord, e.g. ['ctrl','s'].",
        "parameters": {"type": "object",
            "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"]}}},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click at absolute screen coordinates. Use look_at_screen first.",
        "parameters": {"type": "object",
            "properties": {
                "x": {"type": "integer"},
                "y": {"type": "integer"},
                "button": {"type": "string", "enum": ["left", "right", "middle"]},
                "clicks": {"type": "integer"}},
            "required": ["x", "y"]}}},
    {"type": "function", "function": {
        "name": "move_mouse",
        "description": "Move mouse to (x, y).",
        "parameters": {"type": "object",
            "properties": {"x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"]}}},
    {"type": "function", "function": {
        "name": "wait",
        "description": "Pause N seconds.",
        "parameters": {"type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"]}}},
    {"type": "function", "function": {
        "name": "get_screen_size",
        "description": "Return primary screen size as 'WxH'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "notepad_save_as",
        "description": "Save current Notepad doc via real Save-As dialog. Auto-creates parent folder. Returns error if not saved.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read up to 4000 chars from a file.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "screenshot",
        "description": "Save a screenshot to a file.",
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run a shell command. Requires confirmation.",
        "parameters": {"type": "object",
            "properties": {"command": {"type": "string"}},
            "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the task is complete.",
        "parameters": {"type": "object",
            "properties": {"summary": {"type": "string"}},
            "required": ["summary"]}}},
]

DISPATCH: dict[str, Callable[..., str]] = {
    "open_app": act_open_app,
    "open_url": act_open_url,
    "create_folder": act_create_folder,
    "focus_window": act_focus_window,
    "look_at_screen": act_look_at_screen,
    "paste_text": act_paste_text,
    "type_text": act_type_text,
    "press_key": act_press_key,
    "hotkey": act_hotkey,
    "click": act_click,
    "move_mouse": act_move_mouse,
    "wait": act_wait,
    "get_screen_size": act_get_screen_size,
    "notepad_save_as": act_notepad_save_as,
    "read_file": act_read_file,
    "screenshot": act_screenshot,
    "run_shell": act_run_shell,
}

REQUIRED: dict[str, set[str]] = {
    t["function"]["name"]: set(t["function"]["parameters"].get("required", []))
    for t in TOOLS
}
ALLOWED: dict[str, set[str]] = {
    t["function"]["name"]: set(t["function"]["parameters"].get("properties", {}).keys())
    for t in TOOLS
}


def safe_dispatch(name: str, args: dict[str, Any]) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"error: unknown tool {name!r}."
    if not isinstance(args, dict):
        return f"error: {name} expects an object, got {type(args).__name__}"

    allowed = ALLOWED.get(name, set())
    extra = set(args) - allowed
    if extra:
        args = {k: v for k, v in args.items() if k in allowed}

    missing = [k for k in REQUIRED.get(name, set())
               if k not in args or args[k] in ("", None)]
    if missing:
        return f"error: {name} missing required argument(s): {missing}."

    try:
        result = fn(**args)
        return str(result)
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}"
    except Exception as e:
        return f"error: {name} raised {type(e).__name__}: {e}"


# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are a computer-control agent on the user's real Windows machine.
You control mouse, keyboard, and can launch apps. You CANNOT write files directly.

KEYBOARD RULES
- For chords use hotkey(["ctrl","s"]). NEVER press_key("ctrl") then press_key("x").
- paste_text for content > ~50 chars; type_text only for short ASCII strings.

SEEING THE SCREEN
- You are text-only; call `look_at_screen` before any coordinate-based click.
- Never guess pixel coordinates blindly.

PATHS AND FOLDERS
- Before saving into a new path, call `create_folder` first.
- notepad_save_as auto-creates parent folders and verifies the file exists.
- If it returns "error: file was NOT created ...", retry: focus_window, then
  notepad_save_as again. If it fails twice, call look_at_screen to see why.

APP SHORTCUTS
- Spotify Liked Songs  → open_url("spotify:collection")
- Spotify search       → open_url("spotify:search:QUERY")
- Web search           → open_url("https://www.google.com/search?q=...")

MANDATORY NOTEPAD WORKFLOW
  1. open_app(name="notepad")
  2. wait(seconds=2)
  3. focus_window(title_substr="Notepad")
  4. paste_text(text="<FULL content>")
  5. create_folder(path="<parent folder>")   # only if it might not exist
  6. notepad_save_as(path="<full absolute path>")
  7. finish(summary="...")  # only after a "saved OK" result

GENERAL RULES
- Every tool call must include all fields marked required.
- If a tool returns "error: ...", read it and correct your next call.
- Never claim success unless the last tool result confirms it.
"""


# ------------------------------------------------------------------
# Agent loop
# ------------------------------------------------------------------
def run_task(task: str) -> None:
    if CONFIG_ERROR:
        log(f"[config] {CONFIG_ERROR}")
        BRIDGE.task_crashed.emit(CONFIG_ERROR)
        return

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        if STOP_EVENT.is_set():
            log("[stopped] user pressed Stop.")
            BRIDGE.task_done.emit("[stopped] user pressed Stop.")
            return

        BRIDGE.step_started.emit(step, MAX_STEPS)
        log(f"[step {step}/{MAX_STEPS}] thinking…")

        try:
            resp, used_model = _chat_with_fallback(
                MODELS,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            if used_model != MODELS[0]:
                log(f"    (served by fallback model: {used_model})")
        except Exception as e:
            log(f"[api error] all planner models failed: {e}")
            BRIDGE.task_crashed.emit(str(e))
            return

        msg = resp.choices[0].message
        content = (msg.content or "").strip()

        if not getattr(msg, "tool_calls", None) and not content:
            log("  ! empty model response; nudging once…")
            messages.append({"role": "assistant", "content": ""})
            messages.append({
                "role": "user",
                "content": ("You returned nothing. Call the next tool, or "
                            "finish(summary=\"...\") if done."),
            })
            continue

        if not getattr(msg, "tool_calls", None):
            log(f"[model said] {content}")
            BRIDGE.task_done.emit(content)
            return

        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            if STOP_EVENT.is_set():
                log("[stopped] user pressed Stop.")
                BRIDGE.task_done.emit("[stopped] user pressed Stop.")
                return

            name = call.function.name
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception as e:
                args = {}
                log(f"  ! could not parse arguments for {name}: {e}")

            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 240:
                preview = preview[:240] + "…"
            log(f"  → {name}({preview})")

            if name == "finish":
                summary = args.get("summary", "")
                log(f"\n[done] {summary}")
                BRIDGE.task_done.emit(summary or "[done]")
                return

            result = safe_dispatch(name, args if isinstance(args, dict) else {})
            for line in str(result).splitlines() or [""]:
                log(f"    ↳ {line}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

    log(f"[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")
    BRIDGE.task_done.emit(f"[stopped] hit MAX_STEPS={MAX_STEPS}")


# ------------------------------------------------------------------
# Worker: agent
# ------------------------------------------------------------------
class AgentThread(QThread):
    def __init__(self, task: str):
        super().__init__()
        self.task = task

    def run(self):
        try:
            run_task(self.task)
        except Exception as e:
            BRIDGE.task_crashed.emit(f"{type(e).__name__}: {e}")


# ------------------------------------------------------------------
# Worker: live desktop preview
# ------------------------------------------------------------------
class PreviewThread(QThread):
    frame = pyqtSignal(QImage)

    def __init__(self, interval_ms: int = 700):
        super().__init__()
        self._interval = interval_ms / 1000.0
        self._running = True

    def run(self):
        while self._running:
            try:
                img = pyautogui.screenshot()
                img = img.convert("RGB")
                w, h = img.size
                data = img.tobytes("raw", "RGB")
                qimg = QImage(data, w, h, w * 3, QImage.Format_RGB888)
                self.frame.emit(qimg.copy())
            except Exception:
                pass
            time.sleep(self._interval)

    def stop(self):
        self._running = False
        self.wait(2000)


# ------------------------------------------------------------------
# Widget: scaled live preview with a green "AI is looking" border
# ------------------------------------------------------------------
class ScreenPreview(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(480, 320)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            "QLabel { background:#111; border:2px solid #333; color:#888; }"
        )
        self.setText("waiting for first frame…")
        self._pix: QPixmap | None = None
        self._looking = False

    def set_frame(self, qimg: QImage) -> None:
        self._pix = QPixmap.fromImage(qimg)
        self._rescale()

    def set_looking(self, looking: bool) -> None:
        self._looking = looking
        self._apply_style()

    def _apply_style(self):
        if self._looking:
            self.setStyleSheet(
                "QLabel { background:#111; border:3px solid #2ecc71; color:#2ecc71; }"
            )
        else:
            self.setStyleSheet(
                "QLabel { background:#111; border:2px solid #333; color:#888; }"
            )

    def _rescale(self) -> None:
        if not self._pix:
            return
        self.setPixmap(self._pix.scaled(
            self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._rescale()


# ------------------------------------------------------------------
# Main window
# ------------------------------------------------------------------
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NaraRouter Agent — live desktop")
        self.resize(1400, 900)

        self.agent_thread: AgentThread | None = None

        # ---- preview ----
        self.preview = ScreenPreview()
        preview_box = QGroupBox("Desktop — what the AI sees")
        pb_layout = QVBoxLayout(preview_box)
        pb_layout.addWidget(self.preview)

        self.looking_label = QLabel("idle")
        self.looking_label.setAlignment(Qt.AlignCenter)
        self.looking_label.setStyleSheet("color:#888; padding:2px;")
        pb_layout.addWidget(self.looking_label)

        # ---- right panel ----
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)

        # task input
        task_box = QGroupBox("Task")
        tl = QVBoxLayout(task_box)
        self.task_input = QLineEdit()
        self.task_input.setPlaceholderText(
            "e.g. open notepad, write a story, save to C:\\...\\export\\Test-02.txt"
        )
        self.task_input.returnPressed.connect(self.start_task)
        tl.addWidget(self.task_input)

        row = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.run_btn.clicked.connect(self.start_task)
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self.stop_task)
        self.stop_btn.setEnabled(False)
        self.clear_btn = QPushButton("Clear log")
        self.clear_btn.clicked.connect(lambda: self.log_view.clear())
        row.addWidget(self.run_btn)
        row.addWidget(self.stop_btn)
        row.addWidget(self.clear_btn)
        tl.addLayout(row)
        rl.addWidget(task_box)

        # log
        log_box = QGroupBox("Agent log")
        ll = QVBoxLayout(log_box)
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 9))
        self.log_view.setStyleSheet("QTextEdit { background:#0d0d0d; color:#ddd; }")
        ll.addWidget(self.log_view)
        rl.addWidget(log_box, 1)

        # ---- splitter ----
        split = QSplitter(Qt.Horizontal)
        split.addWidget(preview_box)
        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([820, 560])

        central = QWidget()
        cl = QVBoxLayout(central)
        cl.setContentsMargins(8, 8, 8, 8)
        cl.addWidget(split)
        self.setCentralWidget(central)

        # ---- status bar ----
        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._status.showMessage(
            f"models: {' → '.join(MODELS)}  |  vision: {' → '.join(VISION_MODELS)}"
            + (f"  |  {CONFIG_ERROR}" if CONFIG_ERROR else "")
        )

        # ---- bridge signals ----
        BRIDGE.log_line.connect(self._append_log)
        BRIDGE.vision_started.connect(self._on_vision_started)
        BRIDGE.vision_finished.connect(self._on_vision_finished)
        BRIDGE.step_started.connect(self._on_step)
        BRIDGE.task_done.connect(self._on_task_done)
        BRIDGE.task_crashed.connect(self._on_task_crashed)

        # ---- preview thread ----
        self.preview_thread = PreviewThread(interval_ms=700)
        self.preview_thread.frame.connect(self.preview.set_frame)
        self.preview_thread.start()

        if CONFIG_ERROR:
            self._append_log(f"[config] {CONFIG_ERROR}")

    # ---- slots ----
    def _append_log(self, text: str) -> None:
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_vision_started(self) -> None:
        self.preview.set_looking(True)
        self.looking_label.setText("🔍 AI is looking…")
        self.looking_label.setStyleSheet("color:#2ecc71; padding:2px;")

    def _on_vision_finished(self) -> None:
        self.preview.set_looking(False)
        self.looking_label.setText("idle")
        self.looking_label.setStyleSheet("color:#888; padding:2px;")

    def _on_step(self, step: int, total: int) -> None:
        self._status.showMessage(
            f"step {step}/{total} — models: {' → '.join(MODELS)}"
        )

    def _on_task_done(self, summary: str) -> None:
        self._append_log(f"\n=== task finished ===\n{summary}\n")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._status.showMessage("task finished")

    def _on_task_crashed(self, err: str) -> None:
        self._append_log(f"[crashed] {err}")
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._status.showMessage("task crashed")

    # ---- actions ----
    def start_task(self) -> None:
        if self.agent_thread and self.agent_thread.isRunning():
            return
        task = self.task_input.text().strip()
        if not task:
            return
        STOP_EVENT.clear()
        self._append_log(f"\n>>> {task}\n")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._status.showMessage("running…")

        self.agent_thread = AgentThread(task)
        self.agent_thread.start()

    def stop_task(self) -> None:
        STOP_EVENT.set()
        self._append_log("[stop requested]")
        self._status.showMessage("stopping…")

    def closeEvent(self, e):
        try:
            STOP_EVENT.set()
            self.preview_thread.stop()
            if self.agent_thread and self.agent_thread.isRunning():
                self.agent_thread.wait(2000)
        finally:
            super().closeEvent(e)


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------
def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()