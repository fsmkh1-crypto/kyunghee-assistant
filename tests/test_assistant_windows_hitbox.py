import ctypes
from collections import deque
from ctypes import wintypes
import sys
import unittest
from unittest.mock import Mock, patch

from assistant_ai.windows_speech_hitbox import (
    SpeechHitbox, _MAX_CLICKS_PER_POLL, _WM_LBUTTONDOWN, _WM_RBUTTONDOWN,
)


class _TkCallbacks:
    """Fail if a native callback attempts to enter any Tk scheduling API."""
    def __init__(self):
        self.in_native = False
        self.callbacks = {}
        self.cancelled = []
        self.serial = 0

    def after(self, delay, callback):
        if self.in_native:
            raise AssertionError("Tk called inside native WndProc")
        self.serial += 1
        token = f"after-{self.serial}"
        self.callbacks[token] = callback
        return token

    def after_idle(self, *args):
        raise AssertionError("Native clicks must not call after_idle")

    def after_cancel(self, token):
        if self.in_native:
            raise AssertionError("Tk called inside native WndProc")
        self.cancelled.append(token)
        self.callbacks.pop(token, None)

    def pump(self):
        token = next(iter(self.callbacks))
        self.callbacks.pop(token)()


class SpeechHitboxQueueTests(unittest.TestCase):
    def setUp(self):
        self.root = _TkCallbacks()
        self.events = []
        self.hitbox = hitbox = SpeechHitbox.__new__(SpeechHitbox)
        hitbox._root = self.root
        hitbox._on_next = lambda: self.events.append("next")
        hitbox._on_dismiss = lambda: self.events.append("dismiss")
        hitbox._hwnd = 123
        hitbox._visible = True
        hitbox._closed = False
        hitbox._registered = False
        hitbox._generation = 0
        hitbox._clicks = deque()
        hitbox._poll_id = None
        hitbox._user32 = Mock()
        self.addCleanup(hitbox.close)

    def click(self, message):
        self.root.in_native = True
        try:
            self.assertEqual(self.hitbox._handle_message(123, message, 0, 0), 0)
        finally:
            self.root.in_native = False

    def test_native_callback_only_enqueues_and_tk_poll_preserves_click_order(self):
        self.click(_WM_LBUTTONDOWN)
        self.click(_WM_RBUTTONDOWN)
        self.assertEqual(self.events, [])
        self.assertEqual(self.root.callbacks, {})
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, ["next", "dismiss"])
        self.assertEqual(len(self.root.callbacks), 1)

    def test_hidden_and_old_generation_clicks_do_not_reach_callbacks(self):
        self.hitbox._schedule_click_poll()
        token = self.hitbox._poll_id
        self.click(_WM_LBUTTONDOWN)
        old_generation = self.hitbox._generation
        self.hitbox.hide()
        self.assertIn(token, self.root.cancelled)
        self.assertEqual(self.root.callbacks, {})
        self.assertFalse(self.hitbox._clicks)
        self.click(_WM_LBUTTONDOWN)
        self.assertFalse(self.hitbox._clicks)
        self.hitbox._visible = True
        self.hitbox._clicks.append((_WM_LBUTTONDOWN, old_generation))
        self.click(_WM_RBUTTONDOWN)
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, ["dismiss"])

    def test_close_cancels_poll_and_discards_late_native_and_timer_callbacks(self):
        self.hitbox._schedule_click_poll()
        late_poll = self.root.callbacks[self.hitbox._poll_id]
        self.click(_WM_LBUTTONDOWN)
        self.hitbox.close()
        self.hitbox.close()
        self.click(_WM_RBUTTONDOWN)
        late_poll()
        self.assertEqual(self.events, [])
        self.assertFalse(self.hitbox._clicks)
        self.assertEqual(self.root.callbacks, {})
        self.hitbox._user32.DestroyWindow.assert_called_once_with(123)

    def test_callback_can_close_hitbox_without_dispatching_following_clicks(self):
        def close_on_next():
            self.events.append("next")
            self.hitbox.close()
        self.hitbox._on_next = close_on_next
        self.hitbox._schedule_click_poll()
        self.click(_WM_LBUTTONDOWN)
        self.click(_WM_RBUTTONDOWN)
        self.root.pump()
        self.assertEqual(self.events, ["next"])
        self.assertEqual(self.root.callbacks, {})

    def test_large_batch_yields_to_tk_and_keeps_remaining_click_order(self):
        expected = []
        for index in range(_MAX_CLICKS_PER_POLL + 3):
            left = index % 2 == 0
            self.click(_WM_LBUTTONDOWN if left else _WM_RBUTTONDOWN)
            expected.append("next" if left else "dismiss")
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, expected[:_MAX_CLICKS_PER_POLL])
        self.assertEqual(len(self.hitbox._clicks), 3)
        self.root.pump()
        self.assertEqual(self.events, expected)

    def test_constructor_registers_poll_outside_native_callback(self):
        with patch("assistant_ai.windows_speech_hitbox.ctypes.WinDLL", create=True), \
                patch.object(SpeechHitbox, "_configure_win32"):
            hitbox = SpeechHitbox(self.root, lambda: None, lambda: None)
        try:
            self.assertIsNotNone(hitbox._poll_id)
            self.root.pump()
            self.assertIsNone(hitbox._poll_id)
            self.assertEqual(self.root.callbacks, {})
        finally:
            hitbox.close()


@unittest.skipUnless(sys.platform == "win32", "Requires the Windows desktop")
class SpeechHitboxTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk

        from assistant_ai.windows_speech_hitbox import SpeechHitbox

        key = "#010203"
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        self.root.geometry("300x160+80+80")
        self.root.configure(bg=key)
        self.root.attributes("-transparentcolor", key)
        self.root.attributes("-topmost", True)
        self.bubble = tk.Canvas(self.root, bg=key, bd=0, highlightthickness=0)
        self.bubble.place(x=25, y=30, width=250, height=100)
        self.bubble.create_text(125, 50, text="Reply", fill="white")
        self.events = []
        self.hitbox = SpeechHitbox(self.root, lambda: self.events.append("next"), lambda: self.events.append("dismiss"))
        self.addCleanup(self.hitbox.close)
        self.root.update()
        self.hitbox.show_over(self.bubble)
        self.root.update()

        self.api = ctypes.WinDLL("user32", use_last_error=True)
        self.api.GetAncestor.argtypes = (wintypes.HWND, wintypes.UINT)
        self.api.GetAncestor.restype = wintypes.HWND
        self.api.WindowFromPoint.argtypes = (wintypes.POINT,)
        self.api.WindowFromPoint.restype = wintypes.HWND
        self.api.GetWindowRect.argtypes = (wintypes.HWND, ctypes.POINTER(wintypes.RECT))
        self.api.GetWindowRect.restype = wintypes.BOOL
        self.api.GetWindow.argtypes = (wintypes.HWND, wintypes.UINT)
        self.api.GetWindow.restype = wintypes.HWND
        self.api.IsWindowVisible.argtypes = (wintypes.HWND,)
        self.api.IsWindowVisible.restype = wintypes.BOOL
        self.api.GetLayeredWindowAttributes.argtypes = (
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.BYTE),
            ctypes.POINTER(wintypes.DWORD),
        )
        self.api.GetLayeredWindowAttributes.restype = wintypes.BOOL
        self.api.GetForegroundWindow.argtypes = ()
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.SendMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.api.SendMessageW.restype = ctypes.c_ssize_t
        self.api.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.api.PostMessageW.restype = wintypes.BOOL

    def _pump_until(self, predicate):
        timeout = self.root.after(2000, self.root.quit)
        def check():
            if predicate():
                self.root.quit()
            else:
                self.root.after(10, check)
        self.root.after(10, check)
        self.root.mainloop()
        self.root.after_cancel(timeout)
        self.assertTrue(predicate(), "Queued Windows clicks did not reach the Tk callback")

    def test_blank_corners_hit_owned_overlay_until_hidden(self):
        rect = wintypes.RECT()
        self.assertTrue(self.api.GetWindowRect(self.bubble.winfo_id(), ctypes.byref(rect)))
        hwnd = self.hitbox._hwnd
        owner = self.api.GetAncestor(self.root.winfo_id(), 2)
        self.assertEqual(self.api.GetWindow(hwnd, 4), owner)  # GW_OWNER
        self.assertTrue(self.api.IsWindowVisible(hwnd))
        overlay = wintypes.RECT()
        self.assertTrue(self.api.GetWindowRect(hwnd, ctypes.byref(overlay)))
        bounds = (rect.left, rect.top, rect.right, rect.bottom)
        self.assertEqual((overlay.left, overlay.top, overlay.right, overlay.bottom), bounds)
        alpha, flags = wintypes.BYTE(), wintypes.DWORD()
        self.assertTrue(self.api.GetLayeredWindowAttributes(hwnd, None, ctypes.byref(alpha), ctypes.byref(flags)))
        self.assertTrue(0 < alpha.value <= 5)
        self.assertEqual(flags.value, 2)  # LWA_ALPHA only, without a color key
        corners = [
            wintypes.POINT(x, y)
            for x in (rect.left + 3, rect.right - 3)
            for y in (rect.top + 3, rect.bottom - 3)
        ]
        for point in corners:
            hit = self.api.WindowFromPoint(point)
            self.assertEqual(self.api.GetAncestor(hit, 2), hwnd)

        self.hitbox.hide()
        self.root.update()
        for point in corners:
            hit = self.api.WindowFromPoint(point)
            self.assertNotEqual(self.api.GetAncestor(hit, 2), hwnd)

        self.hitbox.show_over(self.bubble)
        self.root.update()
        hit = self.api.WindowFromPoint(corners[-1])
        self.assertEqual(self.api.GetAncestor(hit, 2), hwnd)

    def test_windows_button_messages_route_without_changing_foreground(self):
        foreground = self.api.GetForegroundWindow()
        hwnd = self.hitbox._hwnd
        blank_corner = 3 | (3 << 16)
        # Post through the OS queue so Tcl dispatches WndProc from its native
        # message pump. SendMessage from Python misses that re-entry boundary.
        self.assertEqual(self.api.SendMessageW(hwnd, 0x0021, 0, 0), 3)  # MA_NOACTIVATE
        self.assertTrue(self.api.PostMessageW(hwnd, 0x0201, 1, blank_corner))
        self.assertTrue(self.api.PostMessageW(hwnd, 0x0204, 2, blank_corner))
        self._pump_until(lambda: len(self.events) == 2)
        self.assertEqual(self.events, ["next", "dismiss"])
        self.assertEqual(self.api.GetForegroundWindow(), foreground)
