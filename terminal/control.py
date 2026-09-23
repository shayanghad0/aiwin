"""Lock user mouse/keyboard while AI works; ESC x5 breaks the task."""
from __future__ import annotations
import ctypes
import threading
import time
from contextlib import contextmanager
from typing import Iterator

import ctypes.wintypes as wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
WM_KEYDOWN = 0x0100
WM_SYSKEYDOWN = 0x0104
WM_QUIT = 0x0012
VK_ESCAPE = 0x1B
LLKHF_INJECTED = 0x10
LLMHF_INJECTED = 0x02

ESC_LIMIT = 5
ESC_RESET_S = 1.5


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", wintypes.WPARAM),
        ("lParam", wintypes.LPARAM),
        ("time", wintypes.DWORD),
        ("pt", wintypes.POINT),
    ]


LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)

if not hasattr(wintypes, "HHOOK"):
    wintypes.HHOOK = wintypes.HANDLE

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK
user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL
user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL
kernel32.GetCurrentThreadId.argtypes = []
kernel32.GetCurrentThreadId.restype = wintypes.DWORD

_abort = threading.Event()
_session = threading.Event()
_allow_all = 0
_allow_mouse = 0
_esc_count = 0
_esc_last = 0.0
_esc_lock = threading.Lock()
_hook_kb: int | None = None
_hook_ms: int | None = None
_installed = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None
_tid = 0


def is_aborted() -> bool:
    return _abort.is_set()


def reset_abort() -> None:
    _abort.clear()


def request_abort() -> None:
    _abort.set()
    _session.clear()


def _blocked(injected: bool) -> bool:
    if not _session.is_set() or _allow_all > 0 or injected:
        return False
    return True


def _kbd_proc(nCode: int, wParam: int, lParam: int) -> int:
    global _esc_count, _esc_last
    try:
        if nCode >= 0 and _session.is_set() and _allow_all <= 0:
            kb = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
            if not (kb.flags & LLKHF_INJECTED):
                if kb.vkCode == VK_ESCAPE and wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                    now = time.monotonic()
                    with _esc_lock:
                        if now - _esc_last > ESC_RESET_S:
                            _esc_count = 0
                        _esc_count += 1
                        _esc_last = now
                        count = _esc_count
                    if count >= ESC_LIMIT:
                        with _esc_lock:
                            _esc_count = 0
                        request_abort()
                    return 1
                return 1
        return user32.CallNextHookEx(_hook_kb, nCode, wParam, lParam)
    except Exception:
        return 1


def _ms_proc(nCode: int, wParam: int, lParam: int) -> int:
    try:
        if nCode >= 0 and _session.is_set() and _allow_all <= 0 and _allow_mouse <= 0:
            ms = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
            if not (ms.flags & LLMHF_INJECTED):
                return 1
        return user32.CallNextHookEx(_hook_ms, nCode, wParam, lParam)
    except Exception:
        return 1


_kbd_cb = HOOKPROC(_kbd_proc)
_ms_cb = HOOKPROC(_ms_proc)


def _run_hooks() -> None:
    global _hook_kb, _hook_ms, _tid
    _tid = kernel32.GetCurrentThreadId()
    _hook_kb = user32.SetWindowsHookExW(WH_KEYBOARD_LL, _kbd_cb, None, 0)
    _hook_ms = user32.SetWindowsHookExW(WH_MOUSE_LL, _ms_cb, None, 0)
    _installed.set()
    msg = MSG()
    while not _stop.is_set():
        while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
            if msg.message == WM_QUIT:
                _stop.set()
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        time.sleep(0.01)
    if _hook_kb:
        user32.UnhookWindowsHookEx(_hook_kb)
        _hook_kb = None
    if _hook_ms:
        user32.UnhookWindowsHookEx(_hook_ms)
        _hook_ms = None


def begin_ai_session() -> None:
    global _thread, _esc_count, _esc_last
    reset_abort()
    with _esc_lock:
        _esc_count = 0
        _esc_last = 0.0
    _installed.clear()
    _stop.clear()
    _thread = threading.Thread(target=_run_hooks, daemon=True, name="input-lock")
    _thread.start()
    _installed.wait(2.0)
    _session.set()
    print("[input] mouse/keyboard locked — press ESC 5x to break")


def end_ai_session() -> None:
    global _thread, _tid
    _session.clear()
    _stop.set()
    if _tid:
        user32.PostThreadMessageW(_tid, WM_QUIT, 0, 0)
    if _thread and _thread.is_alive():
        _thread.join(timeout=1.0)
    _thread = None
    _tid = 0


@contextmanager
def temporary_unlock() -> Iterator[None]:
    global _allow_all
    _allow_all += 1
    try:
        yield
    finally:
        _allow_all -= 1


@contextmanager
def allow_mouse() -> Iterator[None]:
    global _allow_mouse
    _allow_mouse += 1
    try:
        yield
    finally:
        _allow_mouse -= 1
