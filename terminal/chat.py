"""Fallback chat + cost logging."""
from __future__ import annotations
from . import config

_TASK_USAGE = {"in": 0, "out": 0}


def _chat_with_fallback(models: list[str], **kwargs):
    last_err = None
    for m in models:
        try:
            resp = config.client.chat.completions.create(model=m, **kwargs)
            return resp, m
        except Exception as e:
            last_err = e
            print(f"    ! model {m!r} failed: {e}")
    assert last_err is not None
    raise last_err


def _log_usage(resp, model: str) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    _TASK_USAGE["in"]  += getattr(u, "prompt_tokens", 0) or 0
    _TASK_USAGE["out"] += getattr(u, "completion_tokens", 0) or 0


def _print_task_cost() -> None:
    pin, pout = _TASK_USAGE["in"], _TASK_USAGE["out"]
    line = f"[cost] tokens in={pin} out={pout}"
    if config.PRICE_IN or config.PRICE_OUT:
        rp = pin / 1_000_000 * config.PRICE_IN + pout / 1_000_000 * config.PRICE_OUT
        line += f"  ≈ Rp{rp:,.2f}"
    print(line)
