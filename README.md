# Ai Win

A Python agent that controls your Windows desktop via mouse, keyboard, screen
vision, and app launching. Two entry points: terminal (CLI) and GUI (PyQt5 live preview).

[▶ Watch the demo video](https://github.com/shayanghad0/aiwin/raw/refs/heads/main/Test.mp4)

The File Result

[Result => Test-11](export/Test-11.txt)

## Project structure

```
aiwin/
├── .env            # copy from .env.sample, add your API key
├── main.py         # CLI entry point → terminal.agent
├── gui.py          # GUI entry point → UI.agent
├── export/         # saved output files land here
├── terminal/       # CLI agent package (10 modules)
│   ├── config.py   # env vars, client init, capability flags
│   ├── chat.py     # model fallback loop, cost logging
│   ├── helpers.py  # confirm prompt, screenshot path, devnull
│   ├── apps.py     # open_app, open_url, create_folder, focus_window
│   ├── input.py    # paste_text, type_text, press_key, hotkey
│   ├── mouse.py    # click, move_mouse, wait
│   ├── screen.py   # screenshot, look_at_screen (vision), get_screen_size
│   ├── files.py    # read_file, notepad_save_as
│   ├── shell.py    # run_shell with CLI confirmation
│   └── agent.py    # tool schema, dispatch, SYSTEM_PROMPT, run_task, main
└── UI/             # PyQt5 GUI package (same 10 modules + widgets)
    ├── config.py   # + AgentBridge (thread-safe Qt signals)
    ├── chat.py     # _chat_with_fallback
    ├── helpers.py  # screenshot path helper
    ├── apps.py     # open_app, open_url, create_folder, focus_window
    ├── input.py    # paste_text, type_text, press_key, hotkey
    ├── mouse.py    # click, move_mouse, wait (interruptible)
    ├── screen.py   # screenshot, look_at_screen, get_screen_size
    ├── files.py    # read_file, notepad_save_as
    ├── shell.py    # run_shell with QMessageBox confirmation
    └── agent.py    # tool schema, dispatch, RUNNER, AgentThread, PreviewThread, MainWindow
```

## Quick start

```bash
# 1. Copy env template and fill in your API key
copy .env.sample .env

# 2. Install dependencies
pip install -r requirements.txt

# 3. Run either mode
python main.py          # terminal
python gui.py           # GUI (PyQt5 live desktop preview)
```

## Environment variables

| Variable | Default | Description |
|---|---|---|
| `NARA_API_KEY` | *(required)* | Your NaraRouter API key (`sk-nry-…`). Put it in `.env`. |
| `NARA_BASE_URL` | `https://router.bynara.id/v1` | API endpoint. |
| `NARA_MODEL` | `nemotron-3-super-free,agnes-2.5-flash` | Planner models (fallback chain). |
| `NARA_VISION_MODEL` | `nex-n2.5-pro,agnes-2.5-flash` | Vision models for screen descriptions. |
| `NARA_MAX_STEPS` | `20` | Max tool calls per task before auto-stop. |
| `NARA_CONFIRM` | `1` | Prompt before running shell commands (`1` = yes). |
| `NARA_PRICE_IN` / `NARA_PRICE_OUT` | `0` | Optional cost rates in Rp per 1M tokens. |

## Tools available to the agent

| Tool | What it does |
|---|---|
| `open_app` | Launch an application by name (e.g. `"notepad"`, `"FL64.exe"`). |
| `open_url` | Open a URL or URI scheme (`spotify:collection`, `https://…`). |
| `create_folder` | Create a folder tree (parents included). Call **before** saving into a new path. |
| `focus_window` | Bring a window matching a title substring to the front. |
| `look_at_screen` | Screenshot + vision model → text description of what's on screen. **Call before any coordinate click.** |
| `paste_text` | Paste full clipboard content (Ctrl+V). |
| `type_text` | Type short ASCII strings at current focus (paths, filenames). |
| `press_key` | Press a single key. |
| `hotkey` | Press a chord, e.g. `["ctrl", "s"]`. |
| `click` | Click at absolute (x, y) screen coordinates. |
| `move_mouse` | Move cursor to (x, y). |
| `wait` | Pause N seconds. |
| `get_screen_size` | Return primary screen dimensions as `WxH`. |
| `notepad_save_as` | Save current Notepad document via the real Save-As dialog. Auto-creates parent folders. |
| `read_file` | Read up to 4000 chars from a file. |
| `screenshot` | Save a screenshot to a file. |
| `run_shell` | Run a shell command (requires confirmation when `NARA_CONFIRM=1`). |
| `finish` | End the task with a summary. |

## Agent behavior notes

- The agent **cannot write files directly** — all file creation goes through the target
  app's GUI (e.g. Notepad Save-As).
- Always call `look_at_screen` before using `click(x, y)` — never guess coordinates.
- The mandatory Notepad save workflow:
  1. `open_app("notepad")`
  2. `wait(2)`
  3. `focus_window("Notepad")`
  4. `paste_text(text="<content>")`
  5. `create_folder(path="<parent>")` — only if the folder may not exist
  6. `notepad_save_as(path="<full path>")`
  7. `finish(summary="...")` after a `saved OK` result
- Shell commands trigger a confirmation dialog in both CLI and GUI modes.

## Dependencies

- Python 3.10+
- `python-dotenv`
- `openai` (SDK)
- `pyautogui`
- `pyperclip`
- `pygetwindow`
- `PyQt5` (GUI mode only)

```txt
python-dotenv
openai
pyautogui
pyperclip
pygetwindow
PyQt5
```

## License

Private — built for personal use.
