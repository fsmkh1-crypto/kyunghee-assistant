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
    @classmethod
    def setUpClass(cls):
        directory = cls.enterClassContext(tempfile.TemporaryDirectory())
        cls.enterClassContext(patch.dict(os.environ, {"APPDATA": directory, "PYSTRAY_BACKEND": "dummy"}))
        import app
        def close_owned_logs():
            for handler in list(app.log.handlers):
                filename = getattr(handler, "baseFilename", "")
                if filename and Path(filename).is_relative_to(Path(directory)):
                    app.log.removeHandler(handler)
                    handler.close()
        cls.addClassCleanup(close_owned_logs)

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
        self.assertEqual(bubble.cget("fg"), "#FFFFFF")
        self.assertTrue(any(
            bubble.type(item) == "polygon" and bubble.itemcget(item, "fill") == "#171C25"
            for item in bubble.find_all()
        ))
        self._assert_visible_inside(bubble.text_widget, bubble)
        self._assert_visible_inside(bubble.chat_button, bubble)
        self.assertEqual(bubble.text_widget.cget("state"), "disabled")
        self.assertEqual(bubble.text_widget.get("1.0", "end-1c"), bubble.cget("text"))
        self.assertLessEqual(int(bubble.text_widget.cget("height")), 3)
        self.assertLessEqual(bubble.text_widget.winfo_height(), 3 * bubble._line_height)
        if bubble._has_overflow:
            self._assert_visible_inside(bubble.scrollbar, bubble)
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
        desktop.speech.configure(text="첫째 줄\n둘째 줄")
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
        first = desktop.speech.text_widget.dlineinfo("1.0")
        second = desktop.speech.text_widget.dlineinfo("2.0")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertGreaterEqual(second[1] - first[1], round(root.winfo_fpixels("15p") * 1.4))

        normal = "일반 대사도 긴 글을 유지합니다.\n" * 12
        desktop.speech.configure(text=normal)
        root.update()
        self._assert_speech_layout(desktop, desktop.speech, scale)
        desktop.speech.scroll_to(1)
        root.update()
        self.assertGreater(desktop.speech.text_widget.yview()[0], 0)
        self.assertEqual(desktop.speech.text_widget.yview()[1], 1)

        long_reply = ("첫째 줄\n둘째 줄\n셋째 줄\n넷째 줄\n"
                      + "한글띄어쓰기없이도읽을수있어요" * 15
                      + "\nhttps://example.com/" + "long-url-path/" * 20
                      + "\n\n웹 조회 시각 2026-11-09\n마지막 문장")
        desktop._show_chat_phase("reply", long_reply)
        root.update()
        bubble = desktop._visible_speech()
        self._assert_speech_layout(desktop, bubble, scale)
        self.assertEqual(bubble.cget("text"), long_reply)
        self.assertNotIn("전체 답변 보기", bubble.cget("text"))
        self._click_reply(desktop)
        self.assertIsNone(desktop._assistant_windows.reply_window)
        self.assertIsNone(desktop._assistant_windows.chat_window)
        before = bubble.text_widget.yview()
        bubble.text_widget.event_generate("<MouseWheel>", delta=-120)
        root.update()
        self.assertGreater(bubble.text_widget.yview()[0], before[0])
        self.assertEqual(desktop._chat_phase, "reply")
        self.assertGreater(desktop._assistant_last_chat_at, float("-inf"))
        # Exercise the real scrollbar command, not just its appearance.
        before_scrollbar = bubble.text_widget.index("@0,0")
        bubble.scrollbar.tk.call(bubble.scrollbar.cget("command"), "moveto", 0.5)
        root.update()
        self.assertTrue(bubble.text_widget.compare("@0,0", ">", before_scrollbar))
        bubble.text_widget.focus_force()
        bubble.text_widget.event_generate("<End>")
        root.update()
        self.assertEqual(bubble.text_widget.yview()[1], 1)
        self.assertIsNotNone(bubble.text_widget.dlineinfo("end-2c"))
        desktop._apply_widget_appearance()
        desktop._render_chat_reply(long_reply)
        root.update()
        # Tk refines total pixel estimates lazily for long wrapped paragraphs;
        # the first fraction can change while the visible last line stays put.
        self.assertEqual(bubble.text_widget.yview()[1], 1)
        self.assertIsNotNone(bubble.text_widget.dlineinfo("end-2c"))
        bubble.text_widget.event_generate("<Home>")
        root.update()
        self.assertEqual(bubble.text_widget.yview()[0], 0)
        self.assertEqual(bubble.text_widget.get("1.0", "end-1c"), long_reply)
        bubble.text_widget.event_generate("<Tab>")
        root.update()
        self.assertIs(root.focus_get(), bubble.chat_button)
        bubble.chat_button.event_generate("<Return>")
        root.update()
        chat = desktop._assistant_windows.chat_window
        self.assertIsNotNone(chat)
        self.assertTrue(chat.winfo_viewable())
        self.assertIsNone(desktop._assistant_windows.reply_window)
        desktop._assistant_windows.hide()
        root.update()

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
