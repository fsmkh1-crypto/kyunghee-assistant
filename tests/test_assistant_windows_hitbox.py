import ctypes
from ctypes import wintypes
import sys
import unittest


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
        self.api.GetForegroundWindow.argtypes = ()
        self.api.GetForegroundWindow.restype = wintypes.HWND
        self.api.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        self.api.PostMessageW.restype = wintypes.BOOL

    def test_blank_corners_hit_owned_overlay_until_hidden(self):
        rect = wintypes.RECT()
        self.assertTrue(self.api.GetWindowRect(self.bubble.winfo_id(), ctypes.byref(rect)))
        hwnd = self.api.GetAncestor(self.hitbox._window.winfo_id(), 2)
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
        client = self.hitbox._window.winfo_id()
        blank_corner = 3 | (3 << 16)
        # Post client messages without disturbing the physical cursor or other apps.
        for down, up, mask in ((0x0201, 0x0202, 1), (0x0204, 0x0205, 2)):
            self.assertTrue(self.api.PostMessageW(client, down, mask, blank_corner))
            self.assertTrue(self.api.PostMessageW(client, up, 0, blank_corner))
        self.root.update()
        self.assertEqual(self.events, ["next", "dismiss"])
        self.assertEqual(self.api.GetForegroundWindow(), foreground)
