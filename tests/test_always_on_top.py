"""The real timer shell keeps its window above others, including legacy settings."""
from dataclasses import replace
import os
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch


_DATA = tempfile.TemporaryDirectory(prefix="seunga-topmost-tests-")
os.environ["APPDATA"] = _DATA.name
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

from app import App
from desktop_gallery_final import FinalGalleryDesktopApp
from settings import UserSettings
from state import fresh_state


class AlwaysOnTopTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest("A display is needed for the real Tk timer integration")

    def setUp(self):
        self.legacy = UserSettings(
            always_on_top=False, break_reminders=False, workday_reminders=False,
            custom_dialogue="보관할 대사", personality="playful", builtin_image_set="canonical",
        )
        self.attribute_calls = []
        original_attributes = tk.Tk.attributes

        def attributes(window, *args):
            self.attribute_calls.append(args)
            return original_attributes(window, *args)

        patches = (
            patch("app.load_user_settings", return_value=self.legacy),
            patch("app.load_state", side_effect=lambda _path: fresh_state()),
            patch("app.App._start_tray"),
            patch("desktop_compact.CompactDesktopApp._start_global_hotkey"),
            patch("desktop_compact.should_suppress_overlay_notifications", return_value=False),
            patch("tkinter.Tk.attributes", autospec=True, side_effect=attributes),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        save_patch = patch("app.save_user_settings")
        self.save = save_patch.start()
        self.addCleanup(save_patch.stop)
        self.app = FinalGalleryDesktopApp()
        self.app.root.update()

    def tearDown(self):
        self.app._ai_closed = True
        self.app.ai_service.close()
        for pending in self.app.root.tk.call("after", "info"):
            self.app.root.tk.call("after", "cancel", pending)
        self.app.root.destroy()

    def assert_topmost_requested_without_demotion(self):
        # Xvfb alone has no window manager to report native topmost state. The
        # real Tk call is recorded here; Windows packaging also checks HWND flags.
        writes = [args for args in self.attribute_calls if len(args) >= 2 and args[0] == "-topmost"]
        self.assertIn(("-topmost", True), writes)
        self.assertTrue(all(bool(args[1]) for args in writes), writes)

    def test_legacy_false_starts_topmost_and_setting_is_checked_and_disabled(self):
        self.assertEqual(self.app.preferences, replace(self.legacy, always_on_top=True))
        self.assertTrue(self.app.settings_bool_vars["always_on_top"].get())
        self.assert_topmost_requested_without_demotion()

        def descendants(widget):
            for child in widget.winfo_children():
                yield child
                yield from descendants(child)

        controls = [widget for widget in descendants(self.app.settings_page)
                    if isinstance(widget, tk.Checkbutton) and "항상 위 표시" in widget.cget("text")]
        self.assertEqual(len(controls), 1)
        self.assertEqual(str(controls[0].cget("state")), "disabled")
        self.assertIn("항상 켜짐", controls[0].cget("text"))
        controls[0].invoke()
        self.assertTrue(self.app.settings_bool_vars["always_on_top"].get())

    def test_applying_false_preserves_other_preferences_and_persists_true(self):
        candidate = replace(self.app.preferences, always_on_top=False,
                            break_reminders=True, message_text_size=14, personality="warm")
        self.app.settings_bool_vars["always_on_top"].set(False)
        self.attribute_calls.clear()
        self.app.apply_preferences(candidate)
        self.assertEqual(self.app.preferences, replace(candidate, always_on_top=True))
        self.assertEqual(self.save.call_args.args[1], self.app.preferences)
        self.assertTrue(self.app.settings_bool_vars["always_on_top"].get())
        self.assert_topmost_requested_without_demotion()

    def test_hide_and_show_stay_topmost_even_with_legacy_false_in_memory(self):
        self.app.preferences = replace(self.app.preferences, always_on_top=False)
        self.attribute_calls.clear()
        self.app._emergency_hide()
        self.assertEqual(self.app.root.state(), "withdrawn")
        self.app.show()
        self.app.root.update()
        self.assertTrue(self.app.root.winfo_viewable())
        self.assert_topmost_requested_without_demotion()

        self.attribute_calls.clear()
        self.app.root.withdraw()
        App.show(self.app)
        done = tk.BooleanVar(master=self.app.root, value=False)
        self.app.root.after(80, lambda: done.set(True))
        self.app.root.wait_variable(done)
        self.assert_topmost_requested_without_demotion()

    def test_fullscreen_suppresses_notifications_without_lowering_timer(self):
        self.attribute_calls.clear()
        with patch("desktop_compact.should_suppress_overlay_notifications", return_value=True), \
             patch.object(self.app.break_gate, "defer") as defer, \
             patch.object(self.app, "_destroy_toast") as destroy:
            self.app._sync_presentation_state()
        defer.assert_called_once()
        destroy.assert_called_once()
        self.assertTrue(self.app._presentation_suppressed)
        self.assert_topmost_requested_without_demotion()


if __name__ == "__main__":
    unittest.main()
