#!/usr/bin/env python3
"""
NaraRouter computer-control agent.

- Reads API key / base URL / model from .env
- Prompts you for a task in the terminal
- Uses the LLM to plan, then executes actions locally via pyautogui + subprocess
- Supports OpenAI-style tool calling, with a strict-JSON fallback for models
  that don't advertise tools.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import load_dotenv
from openai import OpenAI

# ---------- Config ----------

load_dotenv()

API_KEY   = os.getenv("NARA_API_KEY", "").strip()
BASE_URL  = os.getenv("NARA_BASE_URL", "https://router.bynara.id/v1").strip()
MODEL     = os.getenv("NARA_MODEL", "agnes-2.5-flash").strip()
MAX_STEPS = int(os.getenv("NARA_MAX_STEPS", "12"))
CONFIRM   = os.getenv("NARA_CONFIRM", "1") not in ("0", "false", "no")

if not API_KEY or not API_KEY.startswith("sk-nry-"):
    sys.exit("NARA_API_KEY missing or malformed. Put it in .env (sk-nry-...).")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)

# Import pyautogui lazily so --help / env errors don't explode on headless boxes.
try:
    import pyautogui  # type: ignore
    pyautogui.FAILSAFE = True   # slam mouse to a corner to abort
    pyautogui.PAUSE = 0.05
    HAS_GUI = True
except Exception as e:  # pragma: no cover
    HAS_GUI = False
    GUI_IMPORT_ERROR = str(e)

# ---------- Local actions (the "hands") ----------

def _confirm(msg: str) -> bool:
    if not CONFIRM:
        return True
    try:
        return input(f"  [confirm] {msg} [y/N] ").strip().lower() in ("y", "yes")
    except EOFError:
        return False


def act_open_app(name: str) -> str:
    """Launch an application by name or path."""
    if not name:
        return "error: empty app name"
    try:
        if os.name == "nt":
            # Try Start menu search first via 'start'
            subprocess.Popen(f'start "" "{name}"', shell=True)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", "-a", name])
        else:
            subprocess.Popen([name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        time.sleep(1.5)
        return f"launched {name}"
    except Exception as e:
        return f"error launching {name}: {e}"


def act_type_text(text: str) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.write(text, interval=0.01)
    return f"typed {len(text)} chars"


def act_press_key(key: str) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.press(key)
    return f"pressed {key}"


def act_hotkey(keys: list[str]) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.hotkey(*keys)
    return f"hotkey {'+'.join(keys)}"


def act_click(x: int, y: int, button: str = "left", clicks: int = 1) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.click(x=int(x), y=int(y), button=button, clicks=int(clicks))
    return f"clicked ({x},{y})"


def act_move_mouse(x: int, y: int, duration: float = 0.2) -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.moveTo(int(x), int(y), duration=duration)
    return f"moved to ({x},{y})"


def act_save_file(path: str, content: str) -> str:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} chars to {p}"


def act_read_file(path: str) -> str:
    p = Path(path).expanduser()
    if not p.exists():
        return f"error: {p} not found"
    return p.read_text(encoding="utf-8", errors="replace")[:4000]


def act_wait(seconds: float) -> str:
    time.sleep(float(seconds))
    return f"waited {seconds}s"


def act_screenshot(path: str = "screenshot.png") -> str:
    if not HAS_GUI:
        return f"error: GUI unavailable ({GUI_IMPORT_ERROR})"
    pyautogui.screenshot(path)
    return f"saved {path}"


def act_run_shell(command: str) -> str:
    """Dangerous. Always gated by confirm()."""
    if not _confirm(f"run shell command: {command}"):
        return "cancelled by user"
    try:
        out = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=60)
        return (out.stdout or "") + (out.stderr or "") or f"exit {out.returncode}"
    except Exception as e:
        return f"error: {e}"


# ---------- Tool schema (what the LLM can call) ----------

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "open_app",
        "description": "Launch an application by name or full path (e.g. 'notepad', 'FL64.exe').",
        "parameters": {"type": "object", "properties": {
            "name": {"type": "string"}}, "required": ["name"]}}},
    {"type": "function", "function": {
        "name": "type_text",
        "description": "Type text at the current keyboard focus.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string"}}, "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "press_key",
        "description": "Press a single key (enter, tab, esc, f7, ...).",
        "parameters": {"type": "object", "properties": {
            "key": {"type": "string"}}, "required": ["key"]}}},
    {"type": "function", "function": {
        "name": "hotkey",
        "description": "Press a key combination, e.g. ['ctrl','s'].",
        "parameters": {"type": "object", "properties": {
            "keys": {"type": "array", "items": {"type": "string"}}},
            "required": ["keys"]}}},
    {"type": "function", "function": {
        "name": "click",
        "description": "Click at absolute screen coordinates.",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"},
            "button": {"type": "string", "enum": ["left", "right", "middle"]},
            "clicks": {"type": "integer"}}, "required": ["x", "y"]}}},
    {"type": "function", "function": {
        "name": "move_mouse",
        "description": "Move the mouse cursor to (x, y).",
        "parameters": {"type": "object", "properties": {
            "x": {"type": "integer"}, "y": {"type": "integer"}},
            "required": ["x", "y"]}}},
    {"type": "function", "function": {
        "name": "save_file",
        "description": "Write text directly to a file (preferred over GUI typing for saving).",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}, "content": {"type": "string"}},
            "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "read_file",
        "description": "Read up to 4000 chars from a file.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "wait",
        "description": "Pause for N seconds (let an app finish loading).",
        "parameters": {"type": "object", "properties": {
            "seconds": {"type": "number"}}, "required": ["seconds"]}}},
    {"type": "function", "function": {
        "name": "screenshot",
        "description": "Save a screenshot to a file path.",
        "parameters": {"type": "object", "properties": {
            "path": {"type": "string"}}}}},
    {"type": "function", "function": {
        "name": "run_shell",
        "description": "Run a shell command. Requires user confirmation.",
        "parameters": {"type": "object", "properties": {
            "command": {"type": "string"}}, "required": ["command"]}}},
    {"type": "function", "function": {
        "name": "finish",
        "description": "Call when the task is complete. Provide a short summary.",
        "parameters": {"type": "object", "properties": {
            "summary": {"type": "string"}}, "required": ["summary"]}}},
]

DISPATCH: dict[str, Callable[..., str]] = {
    "open_app": act_open_app,
    "type_text": act_type_text,
    "press_key": act_press_key,
    "hotkey": act_hotkey,
    "click": act_click,
    "move_mouse": act_move_mouse,
    "save_file": act_save_file,
    "read_file": act_read_file,
    "wait": act_wait,
    "screenshot": act_screenshot,
    "run_shell": act_run_shell,
}

# ---------- System prompt ----------

SYSTEM_PROMPT = """You are a computer-control agent running on the user's real machine.

You control the mouse, keyboard, file system, and can launch apps. Use the
provided tools. Rules:

1. Prefer `save_file` over typing + Ctrl+S when the goal is "write X to path Y".
   Only drive the GUI when the user explicitly wants to see it happen in Notepad
   or another app.
2. After `open_app`, call `wait` before typing/clicking — apps need time to load.
3. When saving via Notepad: type content, then `hotkey(["ctrl","s"])`, then
   `type_text("<full path>")`, then `press_key("enter")`. If a "file exists"
   dialog is likely, prefer `save_file` instead.
4. FL Studio / DAW note editing: mouse coordinates are fragile. If the user
   wants musical notes, prefer generating a MIDI file with `save_file`
   (write bytes via run_shell if needed) or use the DAW's own import, rather
   than clicking pixels.
5. One tool call per step where possible. Keep reasoning short.
6. When finished, call `finish` with a one-line summary.
7. Never invent file contents the user didn't ask for. Never send data off-box.
"""

# ---------- JSON fallback parser (models without tool support) ----------

JSON_FALLBACK_INSTRUCTION = """
Reply with EXACTLY ONE JSON object and nothing else, in one of these forms:

  {"tool": "open_app", "args": {"name": "notepad"}}
  {"tool": "finish",  "args": {"summary": "..."}}

Available tools: open_app, type_text, press_key, hotkey, click, move_mouse,
save_file, read_file, wait, screenshot, run_shell, finish.
No markdown. No prose. JSON only.
"""

_TOOL_LINE = re.compile(r"^\s*(\w+)\s*\((.*)\)\s*$")


def parse_tool_call_text(text: str) -> dict[str, Any] | None:
    """Best-effort parse of a tool call from free text (JSON fallback)."""
    text = text.strip()
    # strip code fences
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, dict) and "tool" in obj:
            return {"name": obj["tool"], "args": obj.get("args", {}) or {}}
    except Exception:
        pass
    # try to find any {...} block
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json.loads(m.group(0))
            if isinstance(obj, dict) and "tool" in obj:
                return {"name": obj["tool"], "args": obj.get("args", {}) or {}}
        except Exception:
            pass
    # last resort: name(arg=val, ...)
    m = _TOOL_LINE.match(text.splitlines()[-1] if text else "")
    if m:
        name, raw = m.group(1), m.group(2)
        args: dict[str, Any] = {}
        for part in re.split(r",\s*(?=\w+=)", raw):
            if "=" in part:
                k, v = part.split("=", 1)
                v = v.strip().strip("'\"")
                try:
                    args[k.strip()] = json.loads(v)
                except Exception:
                    args[k.strip()] = v
        return {"name": name, "args": args}
    return None


# ---------- Agent loop ----------

def run_task(task: str) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    use_tools = True  # flip to False if the model rejects `tools`

    for step in range(1, MAX_STEPS + 1):
        print(f"\n[step {step}/{MAX_STEPS}] thinking…")

        try:
            if use_tools:
                resp = client.chat.completions.create(
                    model=MODEL,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.2,
                )
            else:
                raise RuntimeError("fallback mode")
        except Exception as e:
            if use_tools:
                print(f"  (tools unsupported or error: {e}) → switching to JSON mode")
                use_tools = False
                messages.append({"role": "system", "content": JSON_FALLBACK_INSTRUCTION})
                resp = client.chat.completions.create(
                    model=MODEL, messages=messages, temperature=0.2,
                )
            else:
                raise

        msg = resp.choices[0].message

        # --- Path A: native tool calls ---
        if use_tools and getattr(msg, "tool_calls", None):
            messages.append(msg.model_dump(exclude_none=True))
            done = False
            for call in msg.tool_calls:
                name = call.function.name
                try:
                    args = json.loads(call.function.arguments or "{}")
                except Exception:
                    args = {}
                print(f"  → {name}({json.dumps(args, ensure_ascii=False)[:200]})")

                if name == "finish":
                    print(f"\n[done] {args.get('summary', '')}")
                    return
                fn = DISPATCH.get(name)
                result = fn(**args) if fn else f"error: unknown tool {name}"
                print(f"    ↳ {result}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": str(result),
                })
            continue

        # --- Path B: JSON fallback ---
        if not use_tools:
            parsed = parse_tool_call_text(msg.content or "")
            messages.append({"role": "assistant", "content": msg.content or ""})
            if not parsed:
                print(f"\n[model said] {msg.content}")
                print("[stopping: could not parse a tool call]")
                return
            name, args = parsed["name"], parsed["args"]
            print(f"  → {name}({json.dumps(args, ensure_ascii=False)[:200]})")
            if name == "finish":
                print(f"\n[done] {args.get('summary', '')}")
                return
            fn = DISPATCH.get(name)
            result = fn(**args) if fn else f"error: unknown tool {name}"
            print(f"    ↳ {result}")
            messages.append({"role": "user", "content": f"tool_result: {result}"})
            continue

        # --- No tool call, no fallback: model just answered ---
        print(f"\n[model said] {msg.content}")
        return

    print(f"\n[stopped] hit MAX_STEPS={MAX_STEPS} without finish()")


# ---------- CLI ----------

def main() -> None:
    print("NaraRouter computer-control agent")
    print(f"  base_url : {BASE_URL}")
    print(f"  model    : {MODEL}")
    print(f"  gui      : {'available' if HAS_GUI else 'UNAVAILABLE — ' + GUI_IMPORT_ERROR}")
    print(f"  confirm  : {'on' if CONFIRM else 'off'}  (NARA_CONFIRM=0 to disable)")
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