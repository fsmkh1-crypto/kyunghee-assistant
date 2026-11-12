"""Complete native text composition from an ordinary Tk callback.

There are deliberately no native callbacks or window-procedure hooks here.
Tk queues IME result characters, so callers must wait for a normal event-loop
turn and an input-edit acknowledgement after ``committed``. An idle callback
alone is not an input barrier. Never copy a composition string
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
    user.GetFocus.argtypes = ()
    user.GetFocus.restype = wintypes.HWND
    user.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
    user.GetAncestor.restype = wintypes.HWND
    user.GetQueueStatus.argtypes = (wintypes.UINT,)
    user.GetQueueStatus.restype = wintypes.DWORD
    return imm, user


def prepare_input(hwnd: int, *, toplevel_hwnd: int | None = None, request_commit: bool = True) -> str:
    """Return ready, no_ime, modifiers, committed, pending, unfocused or failed.

    GCS_COMPSTR reports bytes, not characters. Its contents are never read.
    ``hwnd`` is the logical Text widget, which need not own native focus.
    Tk's Windows caret/IME handling uses its toplevel client HWND. Resolve the
    actual native focus, and never complete input belonging to another window.
    Ctrl/Alt must be released even when no composition remains: an automatic
    completion may already have queued its result. Tk's synthesized result-key
    events inherit modifiers, and its Text bindings ignore Control-key text.
    A caller that already requested completion should only poll, not request
    completion twice. Non-Windows text input uses the normal Tk event loop.
    """
    if os.name != "nt":
        return "ready"
    try:
        imm, user = _libraries()
        expected_root = user.GetAncestor(toplevel_hwnd or hwnd, 2)  # GA_ROOT
        focused = user.GetFocus()
        if not expected_root:
            return "failed"
        if not focused or user.GetAncestor(focused, 2) != expected_root:
            return "unfocused"
        if any((user.GetAsyncKeyState(key) | user.GetKeyState(key)) & 0x8000
               for key in (0x11, 0x12)):  # Ctrl, Alt
            return "modifiers"
        # Current (high-word) queue flags, not the low-word "since last call"
        # flags. Let native input/posted/sent messages run before declaring
        # readiness. Tk timers themselves are deliberately not included.
        if user.GetQueueStatus(0x004F) >> 16:  # QS_KEY/MOUSE/POSTMESSAGE/SENDMESSAGE
            return "pending"
        context_hwnd = focused
        context = imm.ImmGetContext(context_hwnd)
        if not context and toplevel_hwnd and focused != toplevel_hwnd:
            context_hwnd = toplevel_hwnd
            context = imm.ImmGetContext(context_hwnd)
        if not context:
            return "no_ime"  # Confirmed owned native window, no associated IMM context.
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
            return "committed" if imm.ImmNotifyIME(context, 0x0015, 0x0001, 0) else "failed"
        finally:
            imm.ImmReleaseContext(context_hwnd, context)
    except (OSError, AttributeError):
        return "failed"
