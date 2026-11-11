"""Complete native text composition from an ordinary Tk callback.

There are deliberately no native callbacks or window-procedure hooks here.
Tk queues IME result characters, so callers must yield to the event loop after
``committed`` before reading a Text widget. Never copy a composition string
into the widget: the IME/Tk own its insertion and replacement semantics.
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from functools import lru_cache
import os


@lru_cache(maxsize=1)
def _libraries():
    imm = ctypes.WinDLL("imm32", use_last_error=True)
    user = ctypes.WinDLL("user32", use_last_error=True)
    imm.ImmGetContext.argtypes = (wintypes.HWND,)
    imm.ImmGetContext.restype = wintypes.HANDLE
    imm.ImmReleaseContext.argtypes = (wintypes.HWND, wintypes.HANDLE)
    imm.ImmReleaseContext.restype = wintypes.BOOL
    imm.ImmGetCompositionStringW.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD)
    imm.ImmGetCompositionStringW.restype = wintypes.LONG
    imm.ImmNotifyIME.argtypes = (wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD)
    imm.ImmNotifyIME.restype = wintypes.BOOL
    user.GetAsyncKeyState.argtypes = (ctypes.c_int,)
    user.GetAsyncKeyState.restype = ctypes.c_short
    user.GetKeyState.argtypes = (ctypes.c_int,)
    user.GetKeyState.restype = ctypes.c_short
    return imm, user


def prepare_input(hwnd: int, *, request_commit: bool = True) -> str:
    """Return ready, modifiers, committed, pending, or failed.

    GCS_COMPSTR reports bytes, not characters. Its contents are never read.
    Ctrl/Alt must be released before completion: Tk's synthesized result-key
    events inherit modifiers, and its Text bindings ignore Control-key text.
    A caller that already requested completion should only poll, not request
    completion twice. Non-Windows text input uses the normal Tk event loop.
    """
    if os.name != "nt":
        return "ready"
    try:
        imm, user = _libraries()
        context = imm.ImmGetContext(hwnd)
        if not context:
            return "ready"  # No IME input context is associated with this HWND.
        try:
            length = imm.ImmGetCompositionStringW(context, 0x0008, None, 0)  # GCS_COMPSTR
            if length == 0:
                return "ready"
            if length == -1:  # IMM_ERROR_NODATA: composition data is not ready yet.
                return "pending"
            if length < 0:
                return "failed"
            if not request_commit:
                return "pending"
            # Tk uses the queue's GetKeyState when synthesizing result keys;
            # physical release may precede processing its WM_KEYUP message.
            if any((user.GetAsyncKeyState(key) | user.GetKeyState(key)) & 0x8000
                   for key in (0x11, 0x12)):  # Ctrl, Alt
                return "modifiers"
            return "committed" if imm.ImmNotifyIME(context, 0x0015, 0x0001, 0) else "failed"
        finally:
            imm.ImmReleaseContext(hwnd, context)
    except (OSError, AttributeError):
        return "failed"
