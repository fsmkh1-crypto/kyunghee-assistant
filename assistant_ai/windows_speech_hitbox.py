from __future__ import annotations

import ctypes
from collections import deque
from ctypes import wintypes
import tkinter as tk


_ALPHA = 3  # Nonzero alpha participates in Windows layered-window hit testing.
_GA_ROOT = 2
_GW_HWNDPREV = 3
_GWL_EXSTYLE = -20
_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000
_HWND_TOPMOST = -1
_HWND_NOTOPMOST = -2
_LWA_ALPHA = 0x00000002
_SWP_NOACTIVATE = 0x0010
_SWP_SHOWWINDOW = 0x0040
_SWP_NOOWNERZORDER = 0x0200
_SW_HIDE = 0
_WM_MOUSEACTIVATE = 0x0021
_WM_NCHITTEST = 0x0084
_WM_LBUTTONDOWN = 0x0201
_WM_RBUTTONDOWN = 0x0204
_MA_NOACTIVATE = 3
_HTCLIENT = 1
_CLICK_POLL_MS = 25
_MAX_CLICKS_PER_POLL = 32


class SpeechHitbox:
    """An owned Windows mouse target over a color-keyed Tk reply."""

    def __init__(self, root, on_next, on_dismiss):
        self._root = root
        self._on_next = on_next
        self._on_dismiss = on_dismiss
        self._hwnd = None
        self._visible = False
        self._generation = 0
        self._class_name = f"SeungaTimerSpeechHitbox_{id(self):x}"
        self._registered = False
        self._closed = False
        self._clicks = deque()
        self._poll_id = None
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._configure_win32()
        # Register from Python/Tk's normal call stack, never from our WndProc.
        self._schedule_click_poll()

    def _configure_win32(self):
        api = self._user32
        wndproc_type = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                          wintypes.WPARAM, wintypes.LPARAM)

        class WindowClass(ctypes.Structure):
            _fields_ = [
                ("style", wintypes.UINT),
                ("lpfnWndProc", wndproc_type),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HANDLE),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
            ]

        api.RegisterClassW.argtypes = (ctypes.POINTER(WindowClass),)
        api.RegisterClassW.restype = wintypes.ATOM
        api.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
        api.UnregisterClassW.restype = wintypes.BOOL
        api.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
        api.LoadCursorW.restype = wintypes.HANDLE
        api.CreateWindowExW.argtypes = (wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p)
        api.CreateWindowExW.restype = wintypes.HWND
        api.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        api.DefWindowProcW.restype = ctypes.c_ssize_t
        api.DestroyWindow.argtypes = (wintypes.HWND,)
        api.DestroyWindow.restype = wintypes.BOOL
        api.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        api.GetAncestor.restype = wintypes.HWND
        api.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        api.GetWindow.restype = wintypes.HWND
        api.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        api.GetWindowRect.restype = wintypes.BOOL
        api.GetWindowLongW.argtypes = (wintypes.HWND, ctypes.c_int)
        api.GetWindowLongW.restype = wintypes.LONG
        api.SetLayeredWindowAttributes.argtypes = (wintypes.HWND, wintypes.DWORD, wintypes.BYTE, wintypes.DWORD)
        api.SetLayeredWindowAttributes.restype = wintypes.BOOL
        api.SetWindowPos.argtypes = (wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                     ctypes.c_int, ctypes.c_int, wintypes.UINT)
        api.SetWindowPos.restype = wintypes.BOOL
        api.ShowWindow.argtypes = (wintypes.HWND, ctypes.c_int)
        api.ShowWindow.restype = wintypes.BOOL

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HINSTANCE
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        gdi32.GetStockObject.argtypes = (ctypes.c_int,)
        gdi32.GetStockObject.restype = wintypes.HBRUSH
        self._wndproc = wndproc_type(self._handle_message)
        self._window_class = WindowClass(
            lpfnWndProc=self._wndproc,
            hInstance=kernel32.GetModuleHandleW(None),
            hCursor=api.LoadCursorW(None, 32649),  # IDC_HAND
            hbrBackground=gdi32.GetStockObject(4),  # BLACK_BRUSH
            lpszClassName=self._class_name,
        )

    def _handle_message(self, hwnd, message, wparam, lparam):
        if message == _WM_NCHITTEST:
            return _HTCLIENT
        if message == _WM_MOUSEACTIVATE:
            return _MA_NOACTIVATE
        if message in (_WM_LBUTTONDOWN, _WM_RBUTTONDOWN):
            if self._visible and not self._closed:
                # Tcl can invoke this ctypes callback while dispatching Windows
                # messages. Calling *any* Tk API here (even after/after_idle)
                # re-enters _tkinter outside its expected thread-state boundary.
                # Only enqueue plain Python data; Tk owns the polling callback.
                self._clicks.append((message, self._generation))
            return 0
        return self._user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _schedule_click_poll(self):
        if self._closed or self._poll_id is not None:
            return
        try:
            self._poll_id = self._root.after(_CLICK_POLL_MS, self._poll_clicks)
        except tk.TclError:
            self._poll_id = None

    def _poll_clicks(self):
        self._poll_id = None
        if self._closed:
            self._clicks.clear()
            return
        try:
            # Bound each Tk turn while keeping the native click order intact.
            for _ in range(_MAX_CLICKS_PER_POLL):
                if not self._clicks:
                    break
                message, generation = self._clicks.popleft()
                action = self._on_next if message == _WM_LBUTTONDOWN else self._on_dismiss
                self._dispatch_click(action, generation)
        finally:
            if self._visible and not self._closed:
                self._schedule_click_poll()

    def _dispatch_click(self, action, generation):
        if not self._closed and self._visible and generation == self._generation:
            action()

    def _create_window(self, owner):
        api = self._user32
        if not self._registered:
            if not api.RegisterClassW(ctypes.byref(self._window_class)):
                raise ctypes.WinError(ctypes.get_last_error())
            self._registered = True
        style = _WS_EX_LAYERED | _WS_EX_NOACTIVATE | _WS_EX_TOOLWINDOW
        hwnd = api.CreateWindowExW(style, self._class_name, "", _WS_POPUP, 0, 0, 1, 1,
                                   owner, None, self._window_class.hInstance, None)
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        if not api.SetLayeredWindowAttributes(hwnd, 0, _ALPHA, _LWA_ALPHA):
            error = ctypes.get_last_error()
            api.DestroyWindow(hwnd)
            raise ctypes.WinError(error)
        self._hwnd = hwnd

    def _rect(self, hwnd):
        rect = wintypes.RECT()
        if not self._user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise ctypes.WinError(ctypes.get_last_error())
        return rect

    def show_over(self, widget):
        if self._closed:
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
        if self._hwnd is None:
            self._create_window(owner)

        # Sit above the timer and behind any window already above the timer.
        previous = api.GetWindow(owner, _GW_HWNDPREV)
        if previous == self._hwnd:
            previous = api.GetWindow(self._hwnd, _GW_HWNDPREV)
        owner_topmost = api.GetWindowLongW(owner, _GWL_EXSTYLE) & _WS_EX_TOPMOST
        previous_topmost = previous and api.GetWindowLongW(previous, _GWL_EXSTYLE) & _WS_EX_TOPMOST
        if not previous or bool(previous_topmost) != bool(owner_topmost):
            previous = _HWND_TOPMOST if owner_topmost else _HWND_NOTOPMOST
        flags = _SWP_NOACTIVATE | _SWP_NOOWNERZORDER | _SWP_SHOWWINDOW
        if not api.SetWindowPos(self._hwnd, previous, left, top, width, height, flags):
            raise ctypes.WinError(ctypes.get_last_error())
        self._visible = True
        self._schedule_click_poll()

    def hide(self):
        was_visible = self._visible
        self._visible = False
        if was_visible:
            self._generation += 1
        self._clicks.clear()
        if self._poll_id is not None:
            try:
                self._root.after_cancel(self._poll_id)
            except tk.TclError:
                pass
            self._poll_id = None
        if was_visible:
            self._user32.ShowWindow(self._hwnd, _SW_HIDE)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.hide()
        if self._hwnd is not None:
            self._user32.DestroyWindow(self._hwnd)
            self._hwnd = None
        if self._registered:
            self._user32.UnregisterClassW(self._class_name, self._window_class.hInstance)
            self._registered = False
