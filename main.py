#!/usr/bin/env python3
"""
NaraRouter computer-control agent — Notepad GUI edition.

Changes vs. the previous version:
  * `save_file` REMOVED from the tool list (that was the shortcut).
  * New tools: `focus_window`, `paste_text`, `notepad_save_as`.
  * System prompt now forces the Notepad GUI workflow.
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
    import pyperclip  # pip install pyperclip
    HAS_CLIP = True
except Exception as e:
    HAS_CLIP = False
    CLIP_IMPORT_ERROR = str(e)


# ---------- Actions ----------
def _confirm(msg: str) -> bool:
    if not CONFIRM: return True
    try: return input(f"  [confirm] {msg} [y/N] ").strip().lower() in ("y","yes")
    except EOFError: return False


def act_open_app(name: str) -> str:
    if not name: return "error: empty name"
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
    """Bring a window whose title contains `title_substr` to the foreground."""
    try:
        import pygetwindow as gw  # pip install pygetwindow
    except Exception as e:
        return f"error: pygetwindow not installed ({e})"
    wins = gw.getWindowsWithTitle(title_substr)
    if not wins:
        return f"error: no window matching {title_substr!r}"
    w = wins[0]
    try:
        if w.isMinimized: w.restore()
        w.activate()
        time.sleep(0.35)
        return f"focused {w.title!r}"
    except Exception as e:
        return f"error activating: {e}"


def act_paste_text(text: str) -> str:
    """Copy text to clipboard and paste into focused control (fast + Unicode-safe)."""
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    if not HAS_CLIP: return f"error: pyperclip unavailable ({CLIP_IMPORT_ERROR})"
    pyperclip.copy(text)
    time.sleep(0.15)
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.15)
    return f"pasted {len(text)} chars"


def act_type_text(text: str) -> str:
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.write(text, interval=0.01)
    return f"typed {len(text)} chars"


def act_press_key(key: str) -> str:
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.press(key)
    return f"pressed {key}"


def act_hotkey(keys: list[str]) -> str:
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.hotkey(*keys)
    return f"hotkey {'+'.join(keys)}"


def act_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.click(int(x), int(y), button=button, clicks=int(clicks))
    return f"clicked ({x},{y})"


def act_wait(seconds: float) -> str:
    time.sleep(float(seconds)); return f"waited {seconds}s"


def act_screenshot(path: str = "screenshot.png") -> str:
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.screenshot(path); return f"saved {path}"


def act_read_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists(): return f"error: {p} not found"
    return p.read_text(encoding="utf-8", errors="replace")[:4000]


def act_notepad_save_as(path: str) -> str:
    """
    Drive Notepad's real Save-As dialog:
      Ctrl+S  ->  type full path  ->  Enter  ->  Enter (overwrite if prompted)
    """
    if not HAS_GUI: return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.hotkey("ctrl", "s")
    time.sleep(0.9)                       # let the dialog open
    # Filename field has focus in the Windows Save-As dialog.
    pyautogui.write(path, interval=0.01)
    time.sleep(0.25)
    pyautogui.press("enter")
    time.sleep(0.6)                       # possible overwrite confirmation
    pyautogui.press("enter")              # accept "Yes" if it appeared
    time.sleep(0.3)
    return f"Notepad save-as -> {path}"


def act_run_shell(command: str) -> str:
    if not _confirm(f"run shell command: {command}"):
        return "cancelled by user"
    try:
        out = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        return (out.stdout or "") + (out.stderr or "") or f"exit {out.returncode}"
    except Exception as e:
        return f"error: {e}"


# ---------- Tool schema ----------
TOOLS: list[dict[str, Any]] = [
    {"type":"function","function":{"name":"open_app",
        "description":"Launch an application by name (e.g. 'notepad', 'FL64.exe').",
        "parameters":{"type":"object","properties":{"name":{"type":"string"}},"required":["name"]}}},
    {"type":"function","function":{"name":"focus_window",
        "description":"Bring a window whose title contains this substring to the front (e.g. 'Notepad').",
        "parameters":{"type":"object","properties":{"title_substr":{"type":"string"}},"required":["title_substr"]}}},
    {"type":"function","function":{"name":"paste_text",
        "description":"Paste text into the focused control via the clipboard. Prefer this over type_text for long content.",
        "parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"type_text",
        "description":"Type short ASCII text at the current focus (paths, filenames).",
        "parameters":{"type":"object","properties":{"text":{"type":"string"}},"required":["text"]}}},
    {"type":"function","function":{"name":"press_key",
        "description":"Press a single key (enter, tab, esc, f7, ...).",
        "parameters":{"type":"object","properties":{"key":{"type":"string"}},"required":["key"]}}},
    {"type":"function","function":{"name":"hotkey",
        "description":"Press a key combination, e.g. ['ctrl','s'].",
        "parameters":{"type":"object","properties":{"keys":{"type":"array","items":{"type":"string"}}},"required":["keys"]}}},
    {"type":"function","function":{"name":"click",
        "description":"Click at absolute screen coordinates.",
        "parameters":{"type":"object","properties":{
            "x":{"type":"integer"},"y":{"type":"integer"},
            "button":{"type":"string","enum":["left","right","middle"]},
            "clicks":{"type":"integer"}},"required":["x","y"]}}},
    {"type":"function","function":{"name":"wait",
        "description":"Pause N seconds (let an app finish loading).",
        "parameters":{"type":"object","properties":{"seconds":{"type":"number"}},"required":["seconds"]}}},
    {"type":"function","function":{"name":"notepad_save_as",
        "description":"Use Notepad's own Save-As dialog to save the current document to a full path (Ctrl+S -> type path -> Enter). Only call after the content is already typed/pasted into Notepad.",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"read_file",
        "description":"Read up to 4000 chars from a file (for verification).",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}}},
    {"type":"function","function":{"name":"screenshot",
        "description":"Save a screenshot to a file path.",
        "parameters":{"type":"object","properties":{"path":{"type":"string"}}}}},
    {"type":"function","function":{"name":"run_shell",
        "description":"Run a shell command. Requires user confirmation.",
        "parameters":{"type":"object","properties":{"command":{"type":"string"}},"required":["command"]}}},
    {"type":"function","function":{"name":"finish",
        "description":"Call when the task is complete.",
        "parameters":{"type":"object","properties":{"summary":{"type":"string"}},"required":["summary"]}}},
]

DISPATCH: dict[str, Callable[..., str]] = {
    "open_app": act_open_app,
    "focus_window": act_focus_window,
    "paste_text": act_paste_text,
    "type_text": act_type_text,
    "press_key": act_press_key,
    "hotkey": act_hotkey,
    "click": act_click,
    "wait": act_wait,
    "notepad_save_as": act_notepad_save_as,
    "read_file": act_read_file,
    "screenshot": act_screenshot,
    "run_shell": act_run_shell,
    # NOTE: save_file is intentionally absent — this forces the GUI path.
}

# ---------- System prompt ----------
SYSTEM_PROMPT = """You are a computer-control agent on the user's real machine.
You control the mouse, keyboard, and can launch apps. You CANNOT write files
directly — there is no file-writing tool. All file creation must go through
the target application's own GUI (e.g. Notepad's Save-As dialog).

MANDATORY NOTEPAD WORKFLOW
When the user says any variation of "open Notepad, write X, save to Y":
  1. open_app("notepad")
  2. wait(2)
  3. focus_window("Notepad")
  4. paste_text("<the full content>")        # use paste_text, not type_text, for stories
  5. notepad_save_as("<full path with filename>")
  6. finish(...)

RULES
- Never invent a "save_file" or "write_file" tool. If you wish one existed,
  use the Notepad GUI workflow instead.
- Use paste_text for content longer than ~50 chars; use type_text only for
  short ASCII strings like file paths inside dialogs.
- Always focus_window before typing or pasting.
- Only call notepad_save_as AFTER the content is already in the editor.
- If the user asks for a different app (Word, VS Code), use the same pattern:
  open -> focus -> paste -> save via that app's own save flow (Ctrl+S).
- Keep reasoning short. One tool call per step where possible.
- When done, call finish with a one-line summary that mentions the real path.
"""


# ---------- Agent loop ----------
def run_task(task: str) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    for step in range(1, MAX_STEPS + 1):
        print(f"\n[step {step}/{MAX_STEPS}] thinking…")
        resp = client.chat.completions.create(
            model=MODEL, messages=messages, tools=TOOLS, tool_choice="auto",
            temperature=0.2,
        )
        msg = resp.choices[0].message

        if getattr(msg, "tool_calls", None):
            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                name = call.function.name
                try: args = json.loads(call.function.arguments or "{}")
                except Exception: args = {}
                print(f"  → {name}({json.dumps(args, ensure_ascii=False)[:180]})")

                if name == "finish":
                    print(f"\n[done] {args.get('summary','')}")
                    return
                fn = DISPATCH.get(name)
                result = fn(**args) if fn else f"error: unknown tool {name}"
                print(f"    ↳ {result}")
                messages.append({"role":"tool","tool_call_id":call.id,"content":str(result)})
            continue

        print(f"\n[model said] {msg.content}")
        return

    print(f"\n[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")


# ---------- CLI ----------
def main() -> None:
    print("NaraRouter computer-control agent (Notepad GUI edition)")
    print(f"  base_url : {BASE_URL}")
    print(f"  model    : {MODEL}")
    print(f"  gui      : {'available' if HAS_GUI else 'UNAVAILABLE — ' + GUI_IMPORT_ERROR}")
    print(f"  clipboard: {'available' if HAS_CLIP else 'UNAVAILABLE — ' + CLIP_IMPORT_ERROR}")
    print("  type 'exit' or Ctrl+C to quit.\n")

    while True:
        try: task = input("task> ").strip()
        except (EOFError, KeyboardInterrupt): print(); return
        if not task: continue
        if task.lower() in ("exit","quit",":q"): return
        try: run_task(task)
        except KeyboardInterrupt: print("\n[interrupted]")


if __name__ == "__main__":
    main()