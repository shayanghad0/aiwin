"""Fallback chat helper + typewriter logging."""
from __future__ import annotations
import sys
import time
from . import config


def _print_typewriter(text: str, interval: float = 0.02) -> None:
    """Log text character-by-character in the agent thread."""
    for ch in text:
        config.log(ch)
        if ch == '\n':
            time.sleep(0.08)
        else:
            time.sleep(interval)


def _chat_with_fallback(models: list[str], **kwargs):
    last_err = None
    for m in models:
        try:
            resp = config.client.chat.completions.create(model=m, **kwargs)
            return resp, m
        except Exception as e:
            last_err = e
            config.log(f"    ! model {m!r} failed: {e}")
    assert last_err is not None
    raise last_err
