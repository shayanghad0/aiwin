#!/usr/bin/env python3
"""
NaraRouter computer-control agent — free-model fallback + folder-safe save.

Changes vs. previous version:
  * New tool `create_folder` — makes a directory tree, no shell needed.
  * `notepad_save_as` now:
      - creates the parent directory automatically,
      - verifies the file actually exists after the dialog closes,
      - retries once, then returns an honest error if the file is still missing.
  * System prompt forces `create_folder` before any save into a new path.
"""

from __future__ import annotations
import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

# ---------- Config ----------
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

try:
    PRICE_IN  = float(os.getenv("NARA_PRICE_IN",  "0") or 0)
    PRICE_OUT = float(os.getenv("NARA_PRICE_OUT", "0") or 0)
except ValueError:
    PRICE_IN = PRICE_OUT = 0.0

if not API_KEY or not API_KEY.startswith("sk-nry-"):
    sys.exit("NARA_API_KEY missing/malformed (sk-nry-...).")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

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


# ---------- Fallback chat helper ----------
def _chat_with_fallback(models: list[str], **kwargs):
    last_err: Exception | None = None
    for m in models:
        try:
            resp = client.chat.completions.create(model=m, **kwargs)
            return resp, m
        except Exception as e:
            last_err = e
            print(f"    ! model {m!r} failed: {e}")
    assert last_err is not None
    raise last_err


# ---------- Cost log ----------
_TASK_USAGE = {"in": 0, "out": 0}


def _log_usage(resp, model: str) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    _TASK_USAGE["in"]  += getattr(u, "prompt_tokens", 0) or 0
    _TASK_USAGE["out"] += getattr(u, "completion_tokens", 0) or 0


def _print_task_cost() -> None:
    pin, pout = _TASK_USAGE["in"], _TASK_USAGE["out"]
    line = f"[cost] tokens in={pin} out={pout}"
    if PRICE_IN or PRICE_OUT:
        rp = pin / 1_000_000 * PRICE_IN + pout / 1_000_000 * PRICE_OUT
        line += f"  ≈ Rp{rp:,.2f}"
    print(line)


# ---------- Helpers ----------
def _confirm(msg: str) -> bool:
    if not CONFIRM:
        return True
    try:
        return input(f"  [confirm] {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _safe_screenshot_path(path: str | None) -> str:
    if not path:
        return os.path.join(tempfile.gettempdir(), "nara_screen.png")
    p = Path(os.path.expanduser(path))
    if not p.parent.exists():
        p = Path(tempfile.gettempdir()) / p.name
    return str(p)


def _devnull():
    return subprocess.DEVNULL


# ---------- Actions ----------
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


def act_paste_text(text: str) -> str:
    if not text:
        return ("error: paste_text called with empty text. "
                "Provide the full content under the 'text' field.")
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
        return "error: hotkey expects a non-empty list, e.g. ['ctrl','s']"
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
        time.sleep(float(seconds))
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
        _log_usage(r, used)
        text = (r.choices[0].message.content or "(empty vision response)").strip()
        if used != VISION_MODELS[0]:
            text = f"[served by {used}] " + text
        return text
    except Exception as e:
        return f"error: all vision models failed ({e})"


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
    """
    Save the current Notepad document via Ctrl+S -> type path -> Enter.
    * Auto-creates the parent folder.
    * Verifies the file actually exists afterwards (retries once).
    """
    if not path:
        return "error: notepad_save_as called with empty path"
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"

    target = Path(os.path.expanduser(path))
    # 1. Make sure the folder exists BEFORE the dialog opens.
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        return f"error: cannot create parent folder {target.parent}: {e}"

    # 2. Drive the Save-As dialog. Retry once if the file doesn't appear.
    for attempt in (1, 2):
        try:
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.9)
            pyautogui.write(str(target), interval=0.01)
            time.sleep(0.25)
            pyautogui.press("enter")
            time.sleep(0.7)
            # Dismiss possible overwrite / error dialog.
            pyautogui.press("enter")
            time.sleep(0.4)
        except Exception as e:
            return f"error save-as (attempt {attempt}): {e}"

        if target.exists():
            size = target.stat().st_size
            return f"saved OK -> {target} ({size} bytes)"

        # If a modal is stuck, try Esc before retrying.
        try:
            pyautogui.press("esc")
            time.sleep(0.3)
            pyautogui.hotkey("ctrl", "s")
            time.sleep(0.6)
        except Exception:
            pass

    return (f"error: file was NOT created at {target} after 2 attempts. "
            f"The Save-As dialog may have rejected the path or lost focus. "
            f"Verify the folder exists and retry.")


def act_run_shell(command: str) -> str:
    if not command:
        return "error: run_shell called with empty command"
    if not _confirm(f"run shell command: {command}"):
        return "cancelled by user"
    try:
        out = subprocess.run(command, shell=True, capture_output=True,
                             text=True, timeout=60)
        return (out.stdout or "") + (out.stderr or "") or f"exit {out.returncode}"
    except Exception as e:
        return f"error: {e}"


# ---------- Tool schema ----------
TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Launch an application by name (e.g. 'notepad', 'FL64.exe', 'spotify').",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "open_url",
        "description": ("Open a URL or app deep-link. Supports http(s)://, file://, "
                        "and URI schemes like 'spotify:collection', 'spotify:search:QUERY'."),
        "parameters": {"type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "create_folder",
        "description": ("Create a folder (and any missing parents). Call this BEFORE "
                        "saving a file into a path that may not exist yet."),
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
        "description": ("Screenshot -> text description via a vision model. "
                        "USE THIS BEFORE ANY coordinate-based click if unsure."),
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
        "description": "Type short ASCII text at current focus (paths, filenames).",
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
        "description": "Move the mouse cursor to (x, y).",
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
        "description": ("Save the current Notepad document to a full path via the real "
                        "Save-As dialog. Auto-creates the parent folder. Returns an "
                        "error if the file could not be written."),
        "parameters": {"type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read up to 4000 chars from a file (for verification).",
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
        "description": "Run a shell command. Requires user confirmation.",
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


# ---------- Safe dispatcher ----------
def safe_dispatch(name: str, args: dict[str, Any]) -> str:
    fn = DISPATCH.get(name)
    if fn is None:
        return f"error: unknown tool {name!r}. Available: {', '.join(DISPATCH)}"
    if not isinstance(args, dict):
        return f"error: {name} expects an object of arguments, got {type(args).__name__}"

    required = REQUIRED.get(name, set())
    allowed  = ALLOWED.get(name, set())
    extra = set(args) - allowed
    if extra:
        args = {k: v for k, v in args.items() if k in allowed}

    missing = [k for k in required if k not in args or args[k] in ("", None)]
    if missing:
        return (f"error: {name} is missing required argument(s): {missing}. "
                f"Please call {name} again with all required fields.")

    try:
        result = fn(**args)
        if extra:
            return f"{result} (ignored unexpected keys: {sorted(extra)})"
        return str(result)
    except TypeError as e:
        return f"error: bad arguments for {name}: {e}"
    except Exception as e:
        return f"error: {name} raised {type(e).__name__}: {e}"


# ---------- System prompt ----------
SYSTEM_PROMPT = """You are a computer-control agent on the user's real Windows machine.
You control mouse, keyboard, and can launch apps. You CANNOT write files directly —
all file creation goes through the target app's GUI.

KEYBOARD RULES
- For chords use hotkey(["ctrl","s"]). NEVER press_key("ctrl") then press_key("x").
- paste_text for content > ~50 chars; type_text only for short ASCII strings.

SEEING THE SCREEN
- You are text-only; you cannot see images directly.
- Call `look_at_screen` whenever you need to know what's on screen — especially
  BEFORE any coordinate-based click. Never guess pixel coordinates blindly.

PATHS AND FOLDERS — READ CAREFULLY
- Before saving into any path, check whether its parent folder exists.
- If a folder might not exist, call `create_folder` FIRST with the folder path.
- `notepad_save_as` auto-creates the parent folder, but explicit `create_folder`
  is clearer and lets you verify success before touching the save dialog.
- After calling `notepad_save_as`, look at its result:
    * "saved OK -> ..."      => success, you may call finish.
    * "error: file was NOT created ..." => the save failed. Try again:
        1. focus_window("Notepad")
        2. re-run notepad_save_as with the same path
        3. if it fails again, call look_at_screen to see what's blocking

APP SHORTCUTS
- Spotify Liked Songs  → open_url("spotify:collection")
- Spotify search       → open_url("spotify:search:YOUR+QUERY")
- YouTube search       → open_url("https://www.youtube.com/results?search_query=...")
- Web search           → open_url("https://www.google.com/search?q=...")

MANDATORY NOTEPAD WORKFLOW
  1. open_app(name="notepad")
  2. wait(seconds=2)
  3. focus_window(title_substr="Notepad")
  4. paste_text(text="<FULL content>")     # never empty
  5. create_folder(path="<parent folder>") # only if it might not exist
  6. notepad_save_as(path="<full absolute path>")
  7. If the save returned an error, retry as described above.
  8. finish(summary="...")                 # only after saved OK

GENERAL RULES
- Every tool call must include all fields marked required.
- If a tool returns "error: ...", read it and correct your next call.
  Do not repeat the exact same failed call.
- One tool call per step where possible.
- Never claim success unless the last tool result confirms it.
"""


# ---------- Agent loop ----------
def run_task(task: str) -> None:
    _TASK_USAGE["in"] = 0
    _TASK_USAGE["out"] = 0

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        print(f"\n[step {step}/{MAX_STEPS}] thinking…")

        try:
            resp, used_model = _chat_with_fallback(
                MODELS,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            if used_model != MODELS[0]:
                print(f"    (served by fallback model: {used_model})")
            _log_usage(resp, used_model)
        except Exception as e:
            print(f"[api error] all planner models failed: {e}")
            _print_task_cost()
            return

        msg = resp.choices[0].message

        # Empty response with no tool calls -> nudge the model once.
        content = (msg.content or "").strip()
        if not getattr(msg, "tool_calls", None) and not content:
            print("  ! empty model response; nudging once…")
            messages.append({"role": "assistant", "content": ""})
            messages.append({
                "role": "user",
                "content": ("You returned nothing. If the task is not yet finished, "
                            "call the next tool now. If it IS finished, call "
                            "finish(summary=\"...\")."),
            })
            continue

        if not getattr(msg, "tool_calls", None):
            print(f"\n[model said] {content}")
            _print_task_cost()
            return

        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            name = call.function.name
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception as e:
                args = {}
                print(f"  ! could not parse arguments for {name}: {e} (raw={raw_args!r})")

            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "…"
            print(f"  → {name}({preview})")

            if name == "finish":
                print(f"\n[done] {args.get('summary', '')}")
                _print_task_cost()
                return

            result = safe_dispatch(name, args if isinstance(args, dict) else {})
            for line in str(result).splitlines() or [""]:
                print(f"    ↳ {line}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

    print(f"\n[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")
    _print_task_cost()


# ---------- CLI ----------
def main() -> None:
    print("NaraRouter computer-control agent (folder-safe save edition)")
    print(f"  base_url    : {BASE_URL}")
    print(f"  planner     : {' → '.join(MODELS)}")
    print(f"  vision      : {' → '.join(VISION_MODELS)}")
    print(f"  gui         : {'available' if HAS_GUI else 'UNAVAILABLE — ' + GUI_IMPORT_ERROR}")
    print(f"  clipboard   : {'available' if HAS_CLIP else 'UNAVAILABLE — ' + CLIP_IMPORT_ERROR}")
    print(f"  confirm     : {'on' if CONFIRM else 'off'}")
    print(f"  max steps   : {MAX_STEPS}")
    if PRICE_IN or PRICE_OUT:
        print(f"  price       : Rp{PRICE_IN}/1M in, Rp{PRICE_OUT}/1M out")
    print("  type 'exit' or Ctrl+C to quit.\n")

    while True:
        try:
            task = input("task> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not task:
            continue
        if task.lower() in ("exit", "quit", ":q"):
            return
        try:
            run_task(task)
        except KeyboardInterrupt:
            print("\n[interrupted]")


if __name__ == "__main__":
    main()