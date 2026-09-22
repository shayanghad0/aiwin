"""Tool schemas, dispatch, agent loop, preview threads, main window."""
from __future__ import annotations
import json
import sys
import threading
import time
from typing import Any, Callable

from PyQt5.QtCore import Qt, QThread, QTimer, QObject, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap, QFont
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QLineEdit, QPushButton, QGroupBox, QSplitter,
    QStatusBar, QSizePolicy, QMessageBox
)

from . import config
from .chat import _chat_with_fallback, _print_typewriter
from .apps import act_open_app, act_open_url, act_create_folder, act_focus_window
from .input import act_paste_text, act_type_text, act_stream_text, act_press_key, act_hotkey
from .mouse import act_click, act_move_mouse, act_wait
from .screen import act_screenshot, act_look_at_screen, act_get_screen_size
from .files import act_read_file, act_notepad_save_as
from .shell import act_run_shell

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
        "description": "Type short ASCII text at current focus (paths, filenames). Fast (~10ms/char).",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "stream_text",
        "description": "Stream-type text at human-like speed (~35ms/char) into whatever window is focused. Use for writing stories, emails, long content — NEVER use paste_text for long-form writing. Text appears char by char as if a real person is typing.",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}, "interval": {"type": "number", "default": 0.035}},
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
        "description": "Save current Notepad doc via real Save-As dialog. Auto-creates parent folder.",
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
    "stream_text": act_stream_text,
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
- paste_text for content > ~50 chars; type_text only for short ASCII strings (paths, filenames).
- stream_text for long-form writing (stories, essays, emails) — types char by char into whatever window is focused. ALWAYS prefer stream_text over paste_text when writing any substantial text block.

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
  4. stream_text(text="<content paragraph by paragraph>")   # types live, not pasted
     OR paste_text(text="<FULL content>")                     # only for non-writing uses
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
    if config.CONFIG_ERROR:
        config.log(f"[config] {config.CONFIG_ERROR}")
        config.BRIDGE.task_crashed.emit(config.CONFIG_ERROR)
        return

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, config.MAX_STEPS + 1):
        if config.STOP_EVENT.is_set():
            config.log("[stopped] user pressed Stop.")
            config.BRIDGE.task_done.emit("[stopped] user pressed Stop.")
            return

        config.BRIDGE.step_started.emit(step, config.MAX_STEPS)
        config.log(f"[step {step}/{config.MAX_STEPS}] thinking...")

        try:
            resp, used_model = _chat_with_fallback(
                config.MODELS,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            if used_model != config.MODELS[0]:
                config.log(f"    (served by fallback model: {used_model})")
        except Exception as e:
            config.log(f"[api error] all planner models failed: {e}")
            config.BRIDGE.task_crashed.emit(str(e))
            return

        msg = resp.choices[0].message
        content = (msg.content or "").strip()

        if not getattr(msg, "tool_calls", None) and not content:
            config.log("  ! empty model response; nudging once...")
            messages.append({"role": "assistant", "content": ""})
            messages.append({
                "role": "user",
                "content": ("You returned nothing. Call the next tool, or "
                            "finish(summary=\"...\") if done."),
            })
            continue

        if not getattr(msg, "tool_calls", None):
            config.log(f"[model said]")
            _print_typewriter(content)
            config.BRIDGE.task_done.emit(content)
            return

        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            if config.STOP_EVENT.is_set():
                config.log("[stopped] user pressed Stop.")
                config.BRIDGE.task_done.emit("[stopped] user pressed Stop.")
                return

            name = call.function.name
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception as e:
                args = {}
                config.log(f"  ! could not parse arguments for {name}: {e}")

            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 240:
                preview = preview[:240] + "..."
            config.log(f"  → {name}({preview})")

            if name == "finish":
                summary = args.get("summary", "")
                config.log(f"\n[done] {summary}")
                config.BRIDGE.task_done.emit(summary or "[done]")
                return

            result = safe_dispatch(name, args if isinstance(args, dict) else {})
            for line in str(result).splitlines() or [""]:
                config.log(f"    ↳ {line}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

    config.log(f"[stopped] hit MAX_STEPS={config.MAX_STEPS} without finish()")
    config.BRIDGE.task_done.emit(f"[stopped] hit MAX_STEPS={config.MAX_STEPS}")


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
            config.BRIDGE.task_crashed.emit(f"{type(e).__name__}: {e}")


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
                import pyautogui
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
# Widget: scaled live preview with green "AI is looking" border
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
        self.setText("waiting for first frame...")
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
            f"models: {' → '.join(config.MODELS)}  |  vision: {' → '.join(config.VISION_MODELS)}"
            + (f"  |  {config.CONFIG_ERROR}" if config.CONFIG_ERROR else "")
        )

        # ---- bridge signals ----
        config.BRIDGE.log_line.connect(self._append_log)
        config.BRIDGE.vision_started.connect(self._on_vision_started)
        config.BRIDGE.vision_finished.connect(self._on_vision_finished)
        config.BRIDGE.step_started.connect(self._on_step)
        config.BRIDGE.task_done.connect(self._on_task_done)
        config.BRIDGE.task_crashed.connect(self._on_task_crashed)

        # ---- preview thread ----
        self.preview_thread = PreviewThread(interval_ms=700)
        self.preview_thread.frame.connect(self.preview.set_frame)
        self.preview_thread.start()

        if config.CONFIG_ERROR:
            self._append_log(f"[config] {config.CONFIG_ERROR}")

    # ---- slots ----
    def _append_log(self, text: str) -> None:
        self.log_view.append(text)
        sb = self.log_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _on_vision_started(self) -> None:
        self.preview.set_looking(True)
        self.looking_label.setText("AI is looking...")
        self.looking_label.setStyleSheet("color:#2ecc71; padding:2px;")

    def _on_vision_finished(self) -> None:
        self.preview.set_looking(False)
        self.looking_label.setText("idle")
        self.looking_label.setStyleSheet("color:#888; padding:2px;")

    def _on_step(self, step: int, total: int) -> None:
        self._status.showMessage(
            f"step {step}/{total} — models: {' → '.join(config.MODELS)}"
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
        config.STOP_EVENT.clear()
        self._append_log(f"\n>>> {task}\n")
        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._status.showMessage("running...")

        self.agent_thread = AgentThread(task)
        self.agent_thread.start()

    def stop_task(self) -> None:
        config.STOP_EVENT.set()
        self._append_log("[stop requested]")
        self._status.showMessage("stopping...")

    def closeEvent(self, e):
        try:
            config.STOP_EVENT.set()
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
