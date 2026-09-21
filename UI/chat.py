"""Fallback chat helper."""
from . import config


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
