import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


class ReadabilitySettingsTests(unittest.TestCase):
    def test_old_default_fonts_migrate_without_replacing_custom_settings(self):
        from settings import settings_from_dict

        old = {
            "schema_version": 7, "time_text_size": 16, "status_text_size": 9, "message_text_size": 11,
            "time_text_color": "#13A45C", "status_text_color": "#11854B", "message_text_color": "#E05A88",
            "show_status": False,
        }
        defaults = settings_from_dict(old)
        self.assertEqual((defaults.time_text_size, defaults.status_text_size, defaults.message_text_size), (22, 14, 15))
        self.assertEqual((defaults.time_text_color, defaults.status_text_color, defaults.message_text_color), ("#FFFFFF",) * 3)
        self.assertFalse(defaults.show_status)

        custom = settings_from_dict({**old, "time_text_size": 19, "message_text_color": "#AABBCC"})
        self.assertEqual(custom.time_text_size, 19)
        self.assertEqual(custom.message_text_color, "#AABBCC")
        current = settings_from_dict({**old, "schema_version": defaults.schema_version})
        self.assertEqual(current.time_text_size, 16)
        self.assertEqual(current.message_text_color, "#E05A88")


@unittest.skipUnless(
    sys.platform == "win32" or os.environ.get("SEUNGA_TK_TEST_DISPLAY") == "1",
    "Requires a Windows desktop or an explicit Tk test display",
)
class WidgetReadabilityTests(unittest.TestCase):
    def _assert_visible_inside(self, widget, parent):
        self.assertTrue(widget.winfo_viewable())
        left = widget.winfo_rootx() - parent.winfo_rootx()
        top = widget.winfo_rooty() - parent.winfo_rooty()
        self.assertGreaterEqual(left, 0)
        self.assertGreaterEqual(top, 0)
        self.assertLessEqual(left + widget.winfo_width(), parent.winfo_width())
        self.assertLessEqual(top + widget.winfo_height(), parent.winfo_height())

    def _assert_speech_layout(self, desktop, bubble, scale):
        self._assert_visible_inside(bubble, desktop.hero)
        self.assertGreaterEqual(bubble.winfo_reqwidth() / scale, 318)
        self.assertLessEqual(bubble.winfo_reqwidth() / scale, 422)
        text_items = [item for item in bubble.find_all() if bubble.type(item) == "text"]
        self.assertTrue(text_items)
        self.assertEqual(bubble.cget("fg"), "#FFFFFF")
        self.assertTrue(any(
            bubble.type(item) == "polygon" and bubble.itemcget(item, "fill") == "#171C25"
            for item in bubble.find_all()
        ))
        for item in text_items:
            left, top, right, bottom = bubble.bbox(item)
            self.assertGreaterEqual(left, 0)
            self.assertGreaterEqual(top, 0)
            self.assertLessEqual(right, bubble.winfo_width())
            self.assertLessEqual(bottom, bubble.winfo_height())
        self.assertLessEqual(
            desktop.character.winfo_rooty() + desktop._character_visible_bounds()[3],
            bubble.winfo_rooty(),
        )

    def _click_reply(self, desktop):
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes

            hitbox = desktop._chat_hitbox
            self.assertIsNotNone(hitbox)
            self.assertIsNotNone(hitbox._hwnd)
            post_message = ctypes.WinDLL("user32").PostMessageW
            post_message.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            post_message.restype = wintypes.BOOL
            self.assertTrue(post_message(hitbox._hwnd, 0x0201, 1, 4 | (4 << 16)))
            desktop.root.after(100, desktop.root.quit)
            desktop.root.mainloop()
        else:
            desktop._visible_speech().event_generate("<Button-1>", x=4, y=4)
        desktop.root.update()

    def test_clock_status_and_speech_fit_at_common_tk_dpi_scales(self):
        import tkinter as tk

        import app
        from desktop_compact import CompactDesktopApp
        from desktop_gallery_final import FinalGalleryDesktopApp
        from settings import UserSettings, save_user_settings
        from windows_display import enable_per_monitor_dpi_awareness

        enable_per_monitor_dpi_awareness()
        create_tk = tk.Tk

        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi), tempfile.TemporaryDirectory() as temp:
                directory = Path(temp)
                settings_path = directory / "settings.json"
                save_user_settings(settings_path, UserSettings(builtin_image_set="01", widget_scale=100, welcome_seen=True))

                def create_root():
                    root = create_tk()
                    root.tk.call("tk", "scaling", dpi / 72)
                    destroy = root.destroy

                    def destroy_test_root():
                        for event_id in root.tk.splitlist(root.tk.call("after", "info")):
                            root.tk.call("after", "cancel", event_id)
                        destroy()

                    root.destroy = destroy_test_root
                    return root

                with (
                    patch.multiple(app, DATA_DIR=directory, SETTINGS_FILE=settings_path, STATE_FILE=directory / "state.json"),
                    patch.object(app.App, "_start_tray"),
                    patch.object(CompactDesktopApp, "_start_global_hotkey"),
                    patch.object(FinalGalleryDesktopApp, "MANUAL_OVERRIDE_FILE", directory / "manual.json"),
                    patch.object(tk, "Tk", create_root),
                ):
                    desktop = FinalGalleryDesktopApp()
                    try:
                        self._check_at_dpi(desktop)
                    finally:
                        desktop.quit()

    def _check_at_dpi(self, desktop):
        root = desktop.root
        scale = float(root.tk.call("tk", "scaling")) * 72 / 96
        desktop.cont.configure(text="08:59:59")
        desktop.main_status.configure(text="집중 중")
        desktop.speech.configure(text="오빠, 차근차근 진행해 봐요.\n다음 단계도 같이 볼게요.")
        desktop._apply_widget_appearance()
        root.update()
        self._assert_visible_inside(desktop.clock, desktop.hero)
        self._assert_visible_inside(desktop.cont, desktop.clock)
        self._assert_visible_inside(desktop.main_status, desktop.clock)
        self.assertEqual(int(desktop.cont._font.cget("size")), 22)
        self.assertEqual(desktop.cont._font.actual("weight"), "bold")
        self.assertEqual(int(desktop.main_status._font.cget("size")), 14)
        self.assertEqual(int(desktop.speech._font.cget("size")), 15)
        self.assertGreaterEqual(desktop.cont._font.metrics("linespace"), root.winfo_fpixels("22p") * 0.8)
        self.assertLessEqual(
            desktop.cont.winfo_rooty() + desktop.cont.winfo_height(), desktop.main_status.winfo_rooty(),
        )
        self._assert_speech_layout(desktop, desktop.speech, scale)
        first, second = desktop.speech.find_withtag("line")
        line_spacing = desktop.speech.coords(second)[1] - desktop.speech.coords(first)[1]
        self.assertGreaterEqual(line_spacing, round(root.winfo_fpixels("15p") * 1.4))

        short_reply = "첫째 줄\n둘째 줄\n셋째 줄\n넷째 줄"
        desktop._show_chat_phase("reply", short_reply)
        root.update()
        self._assert_speech_layout(desktop, desktop._visible_speech(), scale)
        self.assertEqual(desktop._visible_speech().cget("text"), short_reply)
        self._click_reply(desktop)
        self.assertIsNone(desktop._assistant_windows.reply_window)

        long_reply = short_reply + "\n마지막 줄"
        desktop._show_chat_phase("reply", long_reply)
        root.update()
        self._assert_speech_layout(desktop, desktop._visible_speech(), scale)
        self.assertIn("전체 답변 보기", desktop._visible_speech().cget("text"))
        self._click_reply(desktop)
        reader = desktop._assistant_windows.reply_window
        self.assertTrue(reader.winfo_viewable())
        self.assertEqual(reader.text.get("1.0", "end-1c"), long_reply)
        reader.withdraw()

        source_reply = "관측 자료를 확인했어요.\nhttps://example.com/weather"
        desktop._show_chat_phase("reply", source_reply)
        root.update()
        self.assertIn("전체 답변 보기", desktop._visible_speech().cget("text"))
        self._click_reply(desktop)
        self.assertEqual(reader.text.get("1.0", "end-1c"), source_reply)
        self.assertTrue(reader.text.tag_ranges("source"))
        reader.withdraw()

        flags = desktop.display_bool_vars
        for show_time, show_status in ((False, True), (True, False), (False, False)):
            flags["show_time"].set(show_time)
            flags["show_status"].set(show_status)
            desktop._apply_widget_appearance()
            root.update()
            self.assertEqual(desktop.cont.winfo_viewable(), show_time)
            self.assertEqual(desktop.main_status.winfo_viewable(), show_status)
            self.assertEqual(desktop.clock.winfo_viewable(), show_time or show_status)

        flags["show_message"].set(False)
        desktop._apply_widget_appearance()
        root.update()
        self.assertFalse(desktop.speech.winfo_viewable())


if __name__ == "__main__":
    unittest.main()
