import ctypes
from collections import deque
from ctypes import wintypes
import sys
import unittest
from unittest.mock import Mock, patch

from assistant_ai.windows_speech_hitbox import (
    SpeechHitbox, _MAX_CLICKS_PER_POLL, _WM_LBUTTONDOWN, _WM_RBUTTONDOWN, _WM_MOUSEWHEEL,
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
        hitbox._on_scroll = lambda delta: self.events.append(("scroll", delta))
        hitbox._hwnd = 123
        hitbox._target_hwnd = None
        hitbox._visible = True
        hitbox._closed = False
        hitbox._registered = False
        hitbox._generation = 0
        hitbox._clicks = deque()
        hitbox._poll_id = None
        hitbox._user32 = Mock()
        self.addCleanup(hitbox.close)

    def click(self, message, wparam=0):
        self.root.in_native = True
        try:
            self.assertEqual(self.hitbox._handle_message(123, message, wparam, 0), 0)
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

    def test_native_wheel_preserves_signed_delta_and_never_reenters_tk(self):
        self.click(_WM_MOUSEWHEEL, (120 & 0xFFFF) << 16)
        self.click(_WM_LBUTTONDOWN)
        self.click(_WM_MOUSEWHEEL, (-240 & 0xFFFF) << 16)
        self.assertEqual(self.events, [])
        self.assertEqual(self.root.callbacks, {})
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, [("scroll", 120), "next", ("scroll", -240)])

    def test_hidden_wheel_and_stale_generation_wheel_are_discarded(self):
        self.click(_WM_MOUSEWHEEL, (120 & 0xFFFF) << 16)
        generation = self.hitbox._generation
        self.hitbox.hide()
        self.click(_WM_MOUSEWHEEL, (120 & 0xFFFF) << 16)
        self.assertFalse(self.hitbox._clicks)
        self.hitbox._visible = True
        self.hitbox._clicks.append((_WM_MOUSEWHEEL, generation, -120))
        self.click(_WM_MOUSEWHEEL, (-240 & 0xFFFF) << 16)
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, [("scroll", -240)])

    def test_wheel_without_callback_is_ignored(self):
        self.hitbox._on_scroll = None
        self.click(_WM_MOUSEWHEEL, (-120 & 0xFFFF) << 16)
        self.hitbox._schedule_click_poll()
        self.root.pump()
        self.assertEqual(self.events, [])

    def test_switching_speech_surface_discards_old_queued_input(self):
        self.root.winfo_id = lambda: 1
        self.hitbox._target_hwnd = 2
        self.hitbox._user32.GetAncestor.return_value = 10
        self.hitbox._user32.GetWindow.return_value = 0
        self.hitbox._user32.GetWindowLongW.return_value = 0
        widget = Mock()
        widget.winfo_id.return_value = 3
        widget.native_interaction_widgets.return_value = ()
        self.click(_WM_MOUSEWHEEL, (-120 & 0xFFFF) << 16)
        previous_generation = self.hitbox._generation
        with patch.object(self.hitbox, "_rect", return_value=wintypes.RECT(0, 0, 300, 100)), \
                patch.object(self.hitbox, "_set_region"):
            self.hitbox.show_over(widget)
        self.assertEqual(self.hitbox._target_hwnd, 3)
        self.assertGreater(self.hitbox._generation, previous_generation)
        self.assertFalse(self.hitbox._clicks)
        self.root.pump()
        self.assertEqual(self.events, [])

    def test_interactive_rectangles_are_clipped_and_hidden_controls_are_omitted(self):
        visible = Mock()
        hidden = Mock()
        hidden.winfo_viewable.return_value = False
        outside = Mock()
        widget = Mock()
        widget.native_interaction_widgets.return_value = (visible, hidden, outside)
        with patch.object(self.hitbox, "_rect", side_effect=(
            wintypes.RECT(95, 205, 250, 300), wintypes.RECT(500, 500, 600, 600),
        )):
            self.assertEqual(self.hitbox._interaction_exclusions(widget, 100, 200, 120, 80),
                             ((0, 5, 120, 80),))
        hidden.winfo_id.assert_not_called()

    def test_overlay_region_subtracts_controls_and_transfers_only_final_region(self):
        self.hitbox._gdi32 = Mock()
        gdi = self.hitbox._gdi32
        gdi.CreateRectRgn.side_effect = [101, 102, 103]
        self.hitbox._set_region(250, 100, ((10, 10, 180, 80), (185, 10, 210, 80)))
        self.assertEqual(gdi.CombineRgn.call_args_list[0].args, (101, 101, 102, 4))
        self.assertEqual(gdi.CombineRgn.call_args_list[1].args, (101, 101, 103, 4))
        self.assertEqual([call.args for call in gdi.DeleteObject.call_args_list], [(102,), (103,)])
        self.hitbox._user32.SetWindowRgn.assert_called_once_with(123, 101, True)

    def test_failed_region_assignment_releases_all_gdi_handles(self):
        self.hitbox._gdi32 = Mock()
        gdi = self.hitbox._gdi32
        gdi.CreateRectRgn.side_effect = [101, 102]
        self.hitbox._user32.SetWindowRgn.return_value = 0
        with patch("assistant_ai.windows_speech_hitbox.ctypes.WinError", return_value=OSError("region failed"), create=True), \
                patch("assistant_ai.windows_speech_hitbox.ctypes.get_last_error", return_value=0, create=True):
            with self.assertRaisesRegex(OSError, "region failed"):
                self.hitbox._set_region(250, 100, ((10, 10, 180, 80),))
        self.assertEqual([call.args for call in gdi.DeleteObject.call_args_list], [(102,), (101,)])

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

    def _interactive_controls(self, scale=1.0):
        import tkinter as tk

        def pixels(value):
            return round(value * scale)
        self.root.geometry(f"{pixels(400)}x{pixels(260)}+80+80")
        self.bubble.place_configure(x=pixels(20), y=pixels(20),
                                    width=pixels(350), height=pixels(180))
        text = tk.Text(self.bubble, bg="#171C25", fg="white", wrap="word", font=("Segoe UI", 10),
                       bd=0, highlightthickness=0)
        text.insert("1.0", "\n".join(f"읽을 문장 {index}" for index in range(60)))
        text.configure(state="disabled")
        text.place(x=pixels(12), y=pixels(12), width=pixels(250), height=pixels(100))
        scrollbar = tk.Scrollbar(self.bubble, command=text.yview)
        text.configure(yscrollcommand=scrollbar.set)
        scrollbar.place(x=pixels(266), y=pixels(12), width=pixels(18), height=pixels(100))
        button = tk.Button(self.bubble, text="대화", bg="#171C25", fg="white")
        button.place(x=pixels(12), y=pixels(125), width=pixels(100), height=pixels(30))
        controls = (text, scrollbar, button)
        self.bubble.native_interaction_widgets = lambda: controls
        self.root.update()
        self.hitbox.show_over(self.bubble)
        self.root.update()
        return controls

    def test_interactive_children_remain_real_native_mouse_targets_at_four_dpi_scales(self):
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi):
                self.root.tk.call("tk", "scaling", dpi / 72)
                controls = self._interactive_controls(dpi / 96)
                try:
                    owner = self.api.GetAncestor(self.root.winfo_id(), 2)
                    for child in controls:
                        rect = wintypes.RECT()
                        self.assertTrue(self.api.GetWindowRect(child.winfo_id(), ctypes.byref(rect)))
                        point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
                        hit = self.api.WindowFromPoint(point)
                        self.assertNotEqual(self.api.GetAncestor(hit, 2), self.hitbox._hwnd)
                        self.assertEqual(self.api.GetAncestor(hit, 2), owner)
                    border = wintypes.RECT()
                    self.api.GetWindowRect(self.bubble.winfo_id(), ctypes.byref(border))
                    hit = self.api.WindowFromPoint(wintypes.POINT(border.left + 3, border.top + 3))
                    self.assertEqual(self.api.GetAncestor(hit, 2), self.hitbox._hwnd)

                    # Mapping changes rebuild the region; a hidden button must
                    # not leave a permanent hole over the transparent canvas.
                    button = controls[-1]
                    rect = wintypes.RECT()
                    self.api.GetWindowRect(button.winfo_id(), ctypes.byref(rect))
                    former_button = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
                    button.place_forget()
                    self.root.update()
                    self.hitbox.show_over(self.bubble)
                    self.root.update()
                    hit = self.api.WindowFromPoint(former_button)
                    self.assertEqual(self.api.GetAncestor(hit, 2), self.hitbox._hwnd)
                finally:
                    for child in controls:
                        child.destroy()

    def test_posted_native_wheel_scrolls_border_and_embedded_text_without_tk_reentry(self):
        text, scrollbar, button = self._interactive_controls()
        self.hitbox._on_scroll = lambda delta: text.yview_scroll(-int(delta / 120) * 3, "units")
        before = text.yview()[0]
        self.assertTrue(self.api.PostMessageW(self.hitbox._hwnd, _WM_MOUSEWHEEL,
                                             (-120 & 0xFFFF) << 16, 0))
        self._pump_until(lambda: text.yview()[0] > before)

        # Post directly to the real child HWND as Windows now does through the
        # region hole. Its normal Tk Text wheel binding performs the scrolling.
        text.yview_moveto(0)
        text.focus_force()
        self.root.update()
        rect = wintypes.RECT()
        self.api.GetWindowRect(text.winfo_id(), ctypes.byref(rect))
        point = (rect.left + 5) | ((rect.top + 5) << 16)
        self.assertTrue(self.api.PostMessageW(text.winfo_id(), _WM_MOUSEWHEEL,
                                             (-120 & 0xFFFF) << 16, point))
        self._pump_until(lambda: text.yview()[0] > 0)
        self.assertEqual(self.events, [])
