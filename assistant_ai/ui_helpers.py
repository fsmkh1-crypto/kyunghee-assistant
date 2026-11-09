"""Small shared geometry helpers for desktop dialogs."""
from __future__ import annotations
import ctypes
from ctypes import wintypes
import os


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
    parent.update_idletasks()
    window.update_idletasks()
    width, height = window.winfo_width(), window.winfo_height()
    if width <= 1 or height <= 1:
        preferred = getattr(window, "_preferred_size", None)
        if preferred:
            width, height = preferred
        else:
            window.deiconify()
            window.update_idletasks()
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
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        user32.GetAncestor.restype = wintypes.HWND
        user32.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                       ctypes.c_int, ctypes.c_int, wintypes.UINT)
        user32.SetWindowPos.restype = wintypes.BOOL
        hwnd = user32.GetAncestor(window.winfo_id(), 2) or window.winfo_id()
        if not user32.SetWindowPos(hwnd, None, x, y, width, height, 0x0014):
            window.geometry(f"{width}x{height}+{max(0, x)}+{max(0, y)}")
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
