"""Shell command execution with Qt confirmation dialog."""
from __future__ import annotations
import subprocess
import threading
import time

from PyQt5.QtWidgets import QMessageBox
from PyQt5.QtCore import QTimer

from . import config


def act_run_shell(command: str) -> str:
    if not command:
        return "error: run_shell called with empty command"
    if not config.CONFIRM:
        pass  # skip confirmation
    else:
        result_holder = {"ok": False}
        done = threading.Event()

        def ask():
            r = QMessageBox.question(
                None, "Confirm shell command",
                f"Run this shell command?\n\n{command}",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            result_holder["ok"] = (r == QMessageBox.Yes)
            done.set()

        QTimer.singleShot(0, ask)
        done.wait(120)
        if not result_holder["ok"]:
            return "cancelled by user"

    try:
        out = subprocess.run(command, shell=True, capture_output=True,
                             text=True, timeout=60)
        return (out.stdout or "") + (out.stderr or "") or f"exit {out.returncode}"
    except Exception as e:
        return f"error: {e}"
