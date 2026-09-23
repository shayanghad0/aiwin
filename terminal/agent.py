"""Tool schemas, dispatch table, agent loop, CLI entry point."""
from __future__ import annotations
import json
import sys
from typing import Any, Callable

from . import config
from . import control
from .chat import _chat_with_fallback, _log_usage, _print_task_cost, _print_typewriter
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
        "description": "Open a URL or app deep-link. Supports http(s)://, file://, and URI schemes like 'spotify:collection'.",
        "parameters": {"type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]}}},
    {"type": "function", "function": {
        "name": "create_folder",
        "description": "Create a folder (and any missing parents). Call BEFORE saving a file into a new path.",
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
        "description": "Screenshot -> text description via a vision model. USE BEFORE any coordinate-based click.",
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
        "description": "Stream-type text chatbot-style (word bursts, quick with slight pauses after sentences) into whatever window is focused. Use for writing stories, emails, long content into notepad/chat — NEVER use paste_text for long-form writing.",
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
        "description": "Save current Notepad doc via real Save-As dialog. Auto-creates parent folder.",
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


# ------------------------------------------------------------------
# System prompt
# ------------------------------------------------------------------
SYSTEM_PROMPT = """You are a computer-control agent on the user's real Windows machine.
You control mouse, keyboard, and can launch apps. You CANNOT write files directly —
all file creation goes through the target app's GUI.

KEYBOARD RULES
- For chords use hotkey(["ctrl","s"]). NEVER press_key("ctrl") then press_key("x").
- paste_text for content > ~50 chars; type_text only for short ASCII strings (paths, filenames).
- stream_text for long-form writing (stories, essays, emails, messages) — types char by char into whatever window is focused. ALWAYS prefer stream_text over paste_text when writing any substantial text block.

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

APP SHORTCUTS EXAMPLE
- Spotify Liked Songs  → open_url("spotify:collection")
- Spotify search       → open_url("spotify:search:YOUR+QUERY")
- YouTube search       → open_url("https://www.youtube.com/results?search_query=...")
- Web search           → open_url("https://www.google.com/search?q=...")

MANDATORY NOTEPAD WORKFLOW Example
  1. open_app(name="notepad")
  2. wait(seconds=2)
  3. focus_window(title_substr="Notepad")
  4. stream_text(text="<content paragraph by paragraph>")   # types live, not pasted
     OR paste_text(text="<FULL content>")     # only for non-writing uses
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


# ------------------------------------------------------------------
# Agent loop
# ------------------------------------------------------------------
def run_task(task: str) -> None:
    _TASK_USAGE = {"in": 0, "out": 0}
    # Reuse module-level cost accumulators by writing through them
    import terminal.chat as chat_mod
    chat_mod._TASK_USAGE["in"] = 0
    chat_mod._TASK_USAGE["out"] = 0

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": task},
    ]

    control.begin_ai_session()
    try:
        _run_loop(task, messages)
    finally:
        control.end_ai_session()


def _run_loop(task: str, messages: list[dict[str, Any]]) -> None:
    for step in range(1, config.MAX_STEPS + 1):
        if control.is_aborted():
            print("\n[aborted] user pressed ESC 5x — task stopped")
            _print_task_cost()
            return

        print(f"\n[step {step}/{config.MAX_STEPS}] thinking...")

        try:
            resp, used_model = _chat_with_fallback(
                config.MODELS,
                messages=messages,
                tools=TOOLS,
                tool_choice="auto",
                temperature=0.2,
            )
            if used_model != config.MODELS[0]:
                print(f"    (served by fallback model: {used_model})")
            _log_usage(resp, used_model)
        except Exception as e:
            print(f"[api error] all planner models failed: {e}")
            _print_task_cost()
            return

        if control.is_aborted():
            print("\n[aborted] user pressed ESC 5x — task stopped")
            _print_task_cost()
            return

        msg = resp.choices[0].message

        content = (msg.content or "").strip()
        if not getattr(msg, "tool_calls", None) and not content:
            print("  ! empty model response; nudging once...")
            messages.append({"role": "assistant", "content": ""})
            messages.append({
                "role": "user",
                "content": ("You returned nothing. If the task is not yet finished, "
                            "call the next tool now. If it IS finished, call "
                            "finish(summary=\"...\")."),
            })
            continue

        if not getattr(msg, "tool_calls", None):
            print("\n[model said] ", end="", flush=True)
            _print_typewriter(content)
            _print_task_cost()
            return

        messages.append(msg.model_dump(exclude_none=True))

        for call in msg.tool_calls:
            if control.is_aborted():
                print("\n[aborted] user pressed ESC 5x — task stopped")
                _print_task_cost()
                return

            name = call.function.name
            raw_args = call.function.arguments or "{}"
            try:
                args = json.loads(raw_args) if raw_args.strip() else {}
            except Exception as e:
                args = {}
                print(f"  ! could not parse arguments for {name}: {e} (raw={raw_args!r})")

            preview = json.dumps(args, ensure_ascii=False)
            if len(preview) > 200:
                preview = preview[:200] + "..."
            print(f"  → {name}({preview})")

            if name == "finish":
                print(f"\n[done] {args.get('summary', '')}")
                _print_task_cost()
                return

            result = safe_dispatch(name, args if isinstance(args, dict) else {})
            for line in str(result).splitlines() or [""]:
                print(f"    ↳ {line}")
            if control.is_aborted():
                print("\n[aborted] user pressed ESC 5x — task stopped")
                _print_task_cost()
                return
            messages.append({
                "role": "tool",
                "tool_call_id": call.id,
                "content": str(result),
            })

    print(f"\n[stopped] hit MAX_STEPS={config.MAX_STEPS} without finish()")
    _print_task_cost()


# ------------------------------------------------------------------
# CLI entry point
# ------------------------------------------------------------------
def main() -> None:
    print("NaraRouter computer-control agent (folder-safe save edition)")
    print(f"  base_url    : {config.BASE_URL}")
    print(f"  planner     : {' → '.join(config.MODELS)}")
    print(f"  vision      : {' → '.join(config.VISION_MODELS)}")
    print(f"  gui         : {'available' if config.HAS_GUI else 'UNAVAILABLE — ' + config.GUI_IMPORT_ERROR}")
    print(f"  clipboard   : {'available' if config.HAS_CLIP else 'UNAVAILABLE — ' + config.CLIP_IMPORT_ERROR}")
    print(f"  confirm     : {'on' if config.CONFIRM else 'off'}")
    print(f"  max steps   : {config.MAX_STEPS}")
    if config.PRICE_IN or config.PRICE_OUT:
        print(f"  price       : Rp{config.PRICE_IN}/1M in, Rp{config.PRICE_OUT}/1M out")
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
