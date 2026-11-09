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
        # Feed the popup's native client messages without disturbing the physical cursor.
        self.assertEqual(self.api.SendMessageW(hwnd, 0x0021, 0, 0), 3)  # MA_NOACTIVATE
        self.api.SendMessageW(hwnd, 0x0201, 1, blank_corner)
        self.api.SendMessageW(hwnd, 0x0204, 2, blank_corner)
        self.root.update()
        self.assertEqual(self.events, ["next", "dismiss"])
        self.assertEqual(self.api.GetForegroundWindow(), foreground)
