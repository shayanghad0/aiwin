"""Config, env loading, client setup, capability flags, agent bridge."""
from __future__ import annotations

import os
import sys
import threading
from dotenv import load_dotenv
from openai import OpenAI
from PyQt5.QtCore import QObject, pyqtSignal

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
