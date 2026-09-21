"""Config, env loading, client setup, capability flags."""
from __future__ import annotations

import os
import sys
from dotenv import load_dotenv
from openai import OpenAI

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
