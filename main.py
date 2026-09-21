#!/usr/bin/env python3
"""
NaraRouter computer-control agent — with vision helper.

Fixes vs. previous version:
  * New tool `look_at_screen`: screenshots and sends them to a vision model,
    so the text-only planner can actually see the UI.
  * New tool `open_url`: supports app deep-links like spotify:collection.
  * Screenshot path auto-repair: falls back to temp dir if parent missing.
  * open_app no longer leaks "The system cannot find the file ..." to stdout.
  * System prompt: use hotkey([...]) for chords, never press_key twice.
  * MAX_STEPS default bumped to 20.
"""

from __future__ import annotations
import base64, json, os, re, subprocess, sys, tempfile, time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

# ---------- Config ----------
load_dotenv()
API_KEY       = os.getenv("NARA_API_KEY", "").strip()
BASE_URL      = os.getenv("NARA_BASE_URL", "https://router.bynara.id/v1").strip()
MODEL         = os.getenv("NARA_MODEL", "agnes-2.5-flash").strip()
VISION_MODEL  = os.getenv("NARA_VISION_MODEL", "DeepSeek V4 Flash Vision Exp").strip()
MAX_STEPS     = int(os.getenv("NARA_MAX_STEPS", "20"))
CONFIRM       = os.getenv("NARA_CONFIRM", "1") not in ("0", "false", "no")

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


# ---------- Helpers ----------
def _confirm(msg: str) -> bool:
    if not CONFIRM:
        return True
    try:
        return input(f"  [confirm] {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def _safe_screenshot_path(path: str | None) -> str:
    """Return a writable path. Fall back to OS temp dir if the given dir is missing."""
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
            subprocess.Popen(
                f'start "" "{name}"', shell=True,
                stdout=_devnull(), stderr=_devnull(),
            )
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
    """Open an http(s) URL, file path, or app URI scheme like spotify:collection."""
    if not url:
        return "error: open_url called with empty url"
    try:
        if os.name == "nt":
            os.startfile(url)  # handles http, file, and registered URI schemes
        elif sys.platform == "darwin":
            subprocess.Popen(["open", url], stdout=_devnull(), stderr=_devnull())
        else:
            subprocess.Popen(["xdg-open", url], stdout=_devnull(), stderr=_devnull())
        time.sleep(1.5)
        return f"opened {url}"
    except Exception as e:
        return f"error opening {url}: {e}"


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
    """Take a screenshot and ask a vision model to describe it."""
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
        "You are looking at a screenshot of a Windows desktop. "
        "Describe: (a) which window(s) are visible, (b) the main UI elements "
        "and their approximate pixel coordinates (assume a 1920x1080 screen "
        "unless the image tells you otherwise), (c) anything that looks like a "
        "Play button, navigation list, search box, or error dialog. "
        "Be concise — under 200 words."
    )

    try:
        r = client.chat.completions.create(
            model=VISION_MODEL,
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
        return (r.choices[0].message.content or "(empty vision response)").strip()
    except Exception as e:
        return f"error calling vision model {VISION_MODEL!r}: {e}"


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
    try:
        pyautogui.hotkey("ctrl", "s")
        time.sleep(0.9)
        pyautogui.write(path, interval=0.01)
        time.sleep(0.25)
        pyautogui.press("enter")
        time.sleep(0.6)
        pyautogui.press("enter")
        time.sleep(0.3)
        return f"Notepad save-as -> {path}"
    except Exception as e:
        return f"error save-as: {e}"


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
                        "and registered URI schemes like 'spotify:collection' "
                        "(Spotify Liked Songs), 'spotify:search:...', etc. "
                        "Prefer this over GUI navigation when a deep link exists."),
        "parameters": {"type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "Bring a window whose title contains this substring to the front.",
        "parameters": {"type": "object",
            "properties": {"title_substr": {"type": "string"}},
            "required": ["title_substr"]}}},
    {"type": "function", "function": {
        "name": "look_at_screen",
        "description": ("Take a screenshot and get a TEXT description from a vision model. "
                        "USE THIS BEFORE ANY coordinate-based click if you are unsure what "
                        "is on screen. Never guess pixel coordinates blindly."),
        "parameters": {"type": "object",
            "properties": {"question": {"type": "string",
                "description": "Optional. What to look for on screen."}}}}},
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
        "description": "Press ONE key (enter, tab, esc, f7). For combos use hotkey.",
        "parameters": {"type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "hotkey",
        "description": ("Press a chord, e.g. ['ctrl','s'], ['ctrl','shift','n']. "
                        "Use this — do NOT press_key('ctrl') then press_key('x')."),
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
        "description": "Pause N seconds (let an app finish loading).",
        "parameters": {"type": "object",
            "properties": {"seconds": {"type": "number"}},
            "required": ["seconds"]}}},
    {"type": "function", "function": {
        "name": "get_screen_size",
        "description": "Return primary screen size as 'WxH'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "notepad_save_as",
        "description": "Notepad's own Save-As dialog (Ctrl+S → path → Enter).",
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
        "description": "Save a screenshot to a file (use look_at_screen if you want to see it).",
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
there is no file-writing tool. All file creation goes through the target app's GUI.

KEYBOARD RULES
- For chords use hotkey(["ctrl","s"]). NEVER press_key("ctrl") then press_key("x")
  — two separate presses do not form a shortcut.
- Use paste_text for content longer than ~50 chars; type_text only for short ASCII
  strings like paths inside dialogs.

SEEING THE SCREEN
- You are text-only; you cannot see images directly.
- Call `look_at_screen` whenever you need to know what's on screen, especially
  BEFORE any coordinate-based click. Never guess pixel coordinates blindly.
- After acting, if unsure the action worked, call look_at_screen again to verify.

APP SHORTCUTS — prefer these over GUI navigation
- Spotify Liked Songs  → open_url("spotify:collection")
- Spotify search       → open_url("spotify:search:YOUR+QUERY")
- Spotify specific track → open_url("spotify:track:SPOTIFY_TRACK_ID")
- YouTube search       → open_url("https://www.youtube.com/results?search_query=...")
- Any web search       → open_url("https://www.google.com/search?q=...")

MANDATORY NOTEPAD WORKFLOW
  1. open_app(name="notepad")
  2. wait(seconds=2)
  3. focus_window(title_substr="Notepad")
  4. paste_text(text="<FULL content>")     # never call paste_text with no args
  5. notepad_save_as(path="<full absolute path>")
  6. finish(summary="...")

GENERAL RULES
- Every tool call must include all fields marked required in the schema.
- If a tool returns "error: ...", read it and correct your next call.
  Do not repeat the exact same failed call.
- One tool call per step where possible. Keep reasoning short.
- When done, call finish with a one-line summary mentioning the real outcome.
"""


# ---------- Agent loop ----------
def run_task(task: str) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        print(f"\n[step {step}/{MAX_STEPS}] thinking…")
        try:
            resp = client.chat.completions.create(
                model=MODEL,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
        except Exception as e:
            print(f"[api error] {e}")
            return

        msg = resp.choices[0].message

        if not getattr(msg, "tool_calls", None):
            print(f"\n[model said] {msg.content}")
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
                return

            result = safe_dispatch(name, args if isinstance(args, dict) else {})
            # Multi-line results (like look_at_screen) get indented nicely.
            for line in str(result).splitlines() or [""]:
                print(f"    ↳ {line}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

    print(f"\n[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")


# ---------- CLI ----------
def main() -> None:
    print("NaraRouter computer-control agent (vision helper edition)")
    print(f"  base_url    : {BASE_URL}")
    print(f"  model       : {MODEL}")
    print(f"  vision model: {VISION_MODEL}")
    print(f"  gui         : {'available' if HAS_GUI else 'UNAVAILABLE — ' + GUI_IMPORT_ERROR}")
    print(f"  clipboard   : {'available' if HAS_CLIP else 'UNAVAILABLE — ' + CLIP_IMPORT_ERROR}")
    print(f"  confirm     : {'on' if CONFIRM else 'off'}")
    print(f"  max steps   : {MAX_STEPS}")
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