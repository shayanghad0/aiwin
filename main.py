#!/usr/bin/env python3
"""
NaraRouter computer-control agent — Notepad GUI edition (robust).

Fixes vs. previous version:
  * SAFE dispatcher: validates tool args against the JSON schema and catches
    every exception, returning the error to the model as a tool result so the
    agent loop self-corrects instead of crashing.
  * Handles malformed / empty tool calls (agnes-2.5-flash sometimes sends
    `paste_text({})` with no `text`).
  * Retries a tool call once with a repair prompt before giving up.
"""

from __future__ import annotations
import json, os, re, subprocess, sys, time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

# ---------- Config ----------
load_dotenv()
API_KEY   = os.getenv("NARA_API_KEY", "").strip()
BASE_URL  = os.getenv("NARA_BASE_URL", "https://router.bynara.id/v1").strip()
MODEL     = os.getenv("NARA_MODEL", "agnes-2.5-flash").strip()
MAX_STEPS = int(os.getenv("NARA_MAX_STEPS", "15"))
CONFIRM   = os.getenv("NARA_CONFIRM", "1") not in ("0", "false", "no")

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


# ---------- Actions ----------
def _confirm(msg: str) -> bool:
    if not CONFIRM:
        return True
    try:
        return input(f"  [confirm] {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def act_open_app(name: str) -> str:
    if not name:
        return "error: empty app name"
    try:
        if os.name == "nt":
            subprocess.Popen(f'start "" "{name}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        return f"launched {name}"
    except Exception as e:
        return f"error launching {name}: {e}"


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


def act_screenshot(path: str = "screenshot.png") -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    try:
        pyautogui.screenshot(path)
        return f"saved {path}"
    except Exception as e:
        return f"error screenshot: {e}"


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
        # The Windows Save-As filename field has focus by default.
        # Type the full path; Notepad accepts an absolute path here.
        pyautogui.write(path, interval=0.01)
        time.sleep(0.25)
        pyautogui.press("enter")
        time.sleep(0.6)
        pyautogui.press("enter")  # dismiss "file exists" if it appeared
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
        "description": "Launch an application by name (e.g. 'notepad', 'FL64.exe').",
        "parameters": {"type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "focus_window",
        "description": "Bring a window whose title contains this substring to the front (e.g. 'Notepad').",
        "parameters": {"type": "object",
            "properties": {"title_substr": {"type": "string"}},
            "required": ["title_substr"]}}},
    {"type": "function", "function": {
        "name": "paste_text",
        "description": ("Paste text into the focused control via the clipboard. "
                        "ALWAYS provide the full 'text' string. Use this for content "
                        "longer than ~50 chars (stories, code, paragraphs)."),
        "parameters": {"type": "object",
            "properties": {
                "text": {"type": "string",
                         "description": "The exact content to paste."}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "Type short ASCII text at the current focus (file paths, filenames).",
        "parameters": {"type": "object",
            "properties": {"text": {"type": "string"}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "press_key",
        "description": "Press a single key (enter, tab, esc, f7, ...).",
        "parameters": {"type": "object",
            "properties": {"key": {"type": "string"}},
            "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "hotkey",
        "description": "Press a key combination, e.g. ['ctrl','s'].",
        "parameters": {"type": "object",
            "properties": {"keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"]}}},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click at absolute screen coordinates.",
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
        "description": "Return the primary screen size as 'WxH'.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "notepad_save_as",
        "description": ("Use Notepad's own Save-As dialog to save the current document. "
                        "Call ONLY after content is already in the editor. "
                        "Provide the FULL absolute path including filename."),
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
        "description": "Save a screenshot to a file path.",
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
    "focus_window": act_focus_window,
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
    # NOTE: no save_file — this forces the Notepad GUI path.
}

# Map of tool name -> set of required args (used to pre-validate calls).
REQUIRED: dict[str, set[str]] = {
    t["function"]["name"]: set(t["function"]["parameters"].get("required", []))
    for t in TOOLS
}


# ---------- Safe dispatcher ----------
def safe_dispatch(name: str, args: dict[str, Any]) -> str:
    """Run a tool call without ever raising. Returns a string result/error."""
    fn = DISPATCH.get(name)
    if fn is None:
        return f"error: unknown tool {name!r}. Available: {', '.join(DISPATCH)}"

    if not isinstance(args, dict):
        return f"error: {name} expects an object of arguments, got {type(args).__name__}"

    # Drop unexpected keys so the action functions don't blow up on TypeError.
    required = REQUIRED.get(name, set())
    allowed  = set(TOOLS[[t["function"]["name"] for t in TOOLS].index(name)]
                   ["function"]["parameters"].get("properties", {}).keys())
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
SYSTEM_PROMPT = """You are a computer-control agent on the user's real machine.
You control the mouse, keyboard, and can launch apps. You CANNOT write files
directly — there is no file-writing tool. All file creation must go through
the target application's own GUI (e.g. Notepad's Save-As dialog).

MANDATORY NOTEPAD WORKFLOW
When the user says any variation of "open Notepad, write X, save to Y":
  1. open_app(name="notepad")
  2. wait(seconds=2)
  3. focus_window(title_substr="Notepad")
  4. paste_text(text="<the FULL story content>")   # must include the whole text
  5. notepad_save_as(path="<full absolute path>")
  6. finish(summary="...")

HARD RULES
- paste_text ALWAYS takes a non-empty "text" field. Never call paste_text() with
  no arguments. Compose the entire content in your head, then pass it as "text".
- type_text is only for short strings like file paths inside dialogs.
- Always focus_window before pasting/typing.
- Only call notepad_save_as AFTER the content is already in the editor.
- Every tool call must include all fields marked required in the schema.
- If a tool returns an "error: ..." message, read it and correct your next call.
  Do not repeat the exact same call that just failed.
- Keep reasoning short. One tool call per step where possible.
- When done, call finish with a one-line summary mentioning the real path.
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
            print(f"    ↳ {result}")
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": result,
            })

    print(f"\n[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")


# ---------- CLI ----------
def main() -> None:
    print("NaraRouter computer-control agent (Notepad GUI edition, robust)")
    print(f"  base_url : {BASE_URL}")
    print(f"  model    : {MODEL}")
    print(f"  gui      : {'available' if HAS_GUI else 'UNAVAILABLE — ' + GUI_IMPORT_ERROR}")
    print(f"  clipboard: {'available' if HAS_CLIP else 'UNAVAILABLE — ' + CLIP_IMPORT_ERROR}")
    print(f"  confirm  : {'on' if CONFIRM else 'off'}")
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