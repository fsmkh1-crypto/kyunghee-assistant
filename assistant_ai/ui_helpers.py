"""Small shared geometry helpers for desktop dialogs."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os
import tkinter as tk


def window_exists(window):
    """A cached Python widget can outlive its native window or Tcl interpreter."""
    if window is None:
        return False
    try:
        return bool(window.winfo_exists())
    except tk.TclError:
        return False


def clamp_geometry(x, y, width, height, area, margin=12):
    left, top, right, bottom = area
    margin = min(margin, max(0, (right - left - 1) // 2), max(0, (bottom - top - 1) // 2))
    left, top, right, bottom = left + margin, top + margin, right - margin, bottom - margin
    width = max(1, min(int(width), right - left))
    height = max(1, min(int(height), bottom - top))
    return max(left, min(int(x), right - width)), max(top, min(int(y), bottom - height)), width, height


def position_window(window, parent, work_area=None):
    """Keep every reopened dialog in a current monitor's usable area.

    work_area accepts (x, y, width, height), like CompactDesktopApp._best_work_area.
    Callers without a monitor provider use Tk's virtual desktop bounds.
    """
    if not window_exists(parent) or not window_exists(window):
        return None
    parent.update_idletasks()
    # Geometry updates run idle callbacks too: shutdown can destroy a dialog
    # while its original click handler is still on the stack.
    if not window_exists(parent) or not window_exists(window):
        return None
    window.update_idletasks()
    if not window_exists(window):
        return None
    width, height = window.winfo_width(), window.winfo_height()
    if width <= 1 or height <= 1:
        preferred = getattr(window, "_preferred_size", None)
        if preferred:
            width, height = preferred
        else:
            window.deiconify()
            window.update_idletasks()
            if not window_exists(window):
                return None
            width, height = window.winfo_width(), window.winfo_height()
            if width <= 1 or height <= 1:
                width, height = max(300, window.winfo_reqwidth()), max(200, window.winfo_reqheight())
    positioned = getattr(window, "_seunga_positioned", False)
    x = window.winfo_x() if positioned else parent.winfo_rootx() + 24
    y = window.winfo_y() if positioned else parent.winfo_rooty() + 24
    if work_area is None:
        left, top = parent.winfo_vrootx(), parent.winfo_vrooty()
        area = (left, top, left + parent.winfo_vrootwidth(), top + parent.winfo_vrootheight())
    else:
        area = work_area(x, y, width, height)
    x, y, width, height = clamp_geometry(x, y, width, height, area)
    min_width, min_height = window.minsize()
    window.minsize(min(min_width, width), min(min_height, height))
    if os.name == "nt":
        # Tk interprets a negative geometry offset as distance from the far
        # screen edge. Native absolute coordinates preserve left/top monitors.
        window.geometry(f"{width}x{height}")
        window.deiconify()
        window.update_idletasks()
        if not window_exists(window):
            return None
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        for name in ("GetWindowRect", "GetClientRect"):
            function = getattr(user32, name)
            function.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
            function.restype = wintypes.BOOL
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT)
        user32.SetWindowPos.restype = wintypes.BOOL
        hwnd = user32.GetAncestor(window.winfo_id(), 2) or window.winfo_id()

        def frame_size():
            outer, client = wintypes.RECT(), wintypes.RECT()
            if not (user32.GetWindowRect(hwnd, ctypes.byref(outer))
                    and user32.GetClientRect(hwnd, ctypes.byref(client))):
                return 0, 0
            return (max(0, outer.right - outer.left - client.right + client.left),
                    max(0, outer.bottom - outer.top - client.bottom + client.top))

        # Tk geometry/winfo sizes describe the client. SetWindowPos sizes
        # describe the decorated wrapper. Passing one as the other shrank
        # the chat by its borders/caption every time it reopened.
        desired_width, desired_height = width, height
        frame_width, frame_height = frame_size()
        for _ in range(2):
            x, y, outer_width, outer_height = clamp_geometry(
                x, y, desired_width + frame_width, desired_height + frame_height, area,
            )
            width = max(1, outer_width - frame_width)
            height = max(1, outer_height - frame_height)
            min_width, min_height = window.minsize()
            window.minsize(min(min_width, width), min(min_height, height))
            window.geometry(f"{width}x{height}")
            window.update_idletasks()
            if not window_exists(window):
                return None
            # Only Tk owns sizing. Native movement supplies signed absolute
            # coordinates without interpreting a left monitor as an offset.
            if not user32.SetWindowPos(hwnd, None, x, y, 0, 0, 0x0015):
                window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
                break
            window.update_idletasks()
            if not window_exists(window):
                return None
            updated_frame = frame_size()
            if updated_frame == (frame_width, frame_height):
                break
            # A move between monitors can change native DPI/frame metrics.
            # One correction fits the new frame without repeatedly resizing.
            frame_width, frame_height = updated_frame
    else:
        window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
    window._seunga_positioned = True
    try:
        if parent.winfo_viewable():
            window.transient(parent)
        window.attributes("-topmost", bool(parent.attributes("-topmost")))
    except Exception:
        pass
    return x, y, width, height
