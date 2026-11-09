from __future__ import annotations

import ctypes
from ctypes import wintypes
import tkinter as tk


_ALPHA = 0.012
_GA_ROOT = 2
_GW_HWNDPREV = 3
_GWL_EXSTYLE = -20
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_APPWINDOW = 0x00040000
_WS_EX_NOACTIVATE = 0x08000000
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_SWP_NOACTIVATE = 0x0010
_SWP_NOOWNERZORDER = 0x0200


class SpeechHitbox:
    """A mouse target over the reply without changing the color-keyed timer."""

    def __init__(self, root, on_next, on_dismiss):
        self._root = root
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_win32()
        window = tk.Toplevel(root, bg="#181623", bd=0, highlightthickness=0, cursor="hand2", takefocus=False)
        window.withdraw()
        window.overrideredirect(True)
        window.transient(root)
        # Windows skips hit-testing fully transparent layered-window pixels.
        window.attributes("-alpha", _ALPHA)
        window.bind("<Button-1>", lambda _event: on_next())
        window.bind("<Button-3>", lambda _event: on_dismiss())
        self._window = window

    def _configure_win32(self):
        api = self._user32
        api.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        api.GetAncestor.restype = wintypes.HWND
        api.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        api.GetWindow.restype = wintypes.HWND
        api.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        api.GetWindowRect.restype = wintypes.BOOL
        api.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        api.GetWindowLongW.restype = wintypes.LONG
        api.SetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.LONG)
        api.SetWindowLongW.restype = wintypes.LONG
        api.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT)
        api.SetWindowPos.restype = wintypes.BOOL

    def _rect(self, hwnd):
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return rect

    def show_over(self, widget):
        window = self._window
        if window is None:
            return
        if not widget.winfo_viewable():
            self.hide()
            return

        api = self._user32
        owner = api.GetAncestor(self._root.winfo_id(), _GA_ROOT)
        target = self._rect(widget.winfo_id())
        client = self._rect(self._root.winfo_id())
        left = max(target.left, client.left)
        top = max(target.top, client.top)
        width = min(target.right, client.right) - left
        height = min(target.bottom, client.bottom) - top
        if width <= 0 or height <= 0:
            self.hide()
            return

        if window.state() == "withdrawn":
            window.geometry(f"{width}x{height}+{left}+{top}")
            # An override-redirect Tk window skips Tk's Windows focus step.
            window.deiconify()
            window.update_idletasks()
        hwnd = api.GetAncestor(window.winfo_id(), _GA_ROOT)
        style = api.GetWindowLongW(hwnd, _GWL_EXSTYLE)
        mouse_style = (style | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW) & ~_WS_EX_APPWINDOW
        if mouse_style != style:
            ctypes.set_last_error(0)
            if not api.SetWindowLongW(hwnd, _GWL_EXSTYLE, mouse_style) and ctypes.get_last_error():
                raise ctypes.WinError(ctypes.get_last_error())

        # Keep the hitbox just above the timer, even when another app covers it.
        previous = api.GetWindow(owner, _GW_HWNDPREV)
        if previous == hwnd:
            previous = api.GetWindow(hwnd, _GW_HWNDPREV)
        owner_topmost = api.GetWindowLongW(owner, _GWL_EXSTYLE) & _WS_EX_TOPMOST
        previous_topmost = previous and api.GetWindowLongW(previous, _GWL_EXSTYLE) & _WS_EX_TOPMOST
        if not previous or bool(previous_topmost) != bool(owner_topmost):
            previous = _HWND_TOPMOST if owner_topmost else _HWND_NOTOPMOST
        flags = _SWP_NOACTIVATE | _SWP_NOOWNERZORDER
        if not api.SetWindowPos(hwnd, previous, left, top, width, height, flags):
            raise ctypes.WinError(ctypes.get_last_error())

    def hide(self):
        if self._window is not None and self._window.state() != "withdrawn":
            self._window.withdraw()

    def close(self):
        if self._window is not None:
            self._window.destroy()
            self._window = None
