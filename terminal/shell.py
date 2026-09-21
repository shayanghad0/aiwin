"""Shell command execution with confirmation."""
from __future__ import annotations
import subprocess
import time

from . import config
from .helpers import _confirm, _devnull


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
