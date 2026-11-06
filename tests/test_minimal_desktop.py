"""The companion hides timer text while the original timer keeps working."""
from dataclasses import replace
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="seunga-minimal-import-")
os.environ.setdefault("APPDATA", _IMPORT_DATA.name)
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

from desktop_compact import CompactDesktopApp
from settings import UserSettings
from state import fresh_state, load_state


class MinimalMainSurfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest("A display is needed for the real Tk companion")

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="seunga-minimal-main-")
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.legacy = UserSettings(
            show_time=True, show_status=True, show_message=False,
            always_on_top=True,
            break_reminders=False, workday_reminders=False,
            builtin_image_set="canonical", widget_scale=100,
        )
        patches = (
            patch("app.DATA_DIR", self.data),
            patch("app.STATE_FILE", self.data / "state.json"),
            patch("app.SETTINGS_FILE", self.data / "settings.json"),
            patch("app.load_user_settings", return_value=self.legacy),
            patch("app.load_state", side_effect=lambda _path: fresh_state()),
            patch("app.App._start_tray"),
            patch("desktop_compact.USER_IMAGE_DIR", self.data / "images"),
            patch("desktop_compact.USER_IMAGE_SET_DIR", self.data / "image_sets"),
            patch("desktop_compact.CompactDesktopApp._start_global_hotkey"),
            patch("desktop_compact.should_suppress_overlay_notifications", return_value=False),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        save_patch = patch("app.save_user_settings")
        self.save_preferences = save_patch.start()
        self.addCleanup(save_patch.stop)
        self.app = CompactDesktopApp()
        self.app.root.update()

    def tearDown(self):
        for pending in self.app.root.tk.call("after", "info"):
            self.app.root.tk.call("after", "cancel", pending)
        self.app.root.destroy()

    def assert_minimal_surface(self):
        self.app.root.update_idletasks()
        for name in ("clock", "cont", "main_status", "escape_control"):
            widget = getattr(self.app, name)
            self.assertFalse(widget.winfo_ismapped(), name)
            self.assertEqual(widget.winfo_manager(), "", name)
        self.assertTrue(self.app.character.winfo_ismapped())
        self.assertTrue(self.app.speech.winfo_ismapped())
        self.assertIsNotNone(self.app.character_photo)
        self.assertEqual(self.app._clock_layout_width(), 0)

    def test_startup_hides_legacy_metrics_and_keeps_bubble_without_rewriting_preferences(self):
        self.assert_minimal_surface()
        self.assertEqual(self.app.preferences, self.legacy)
        self.save_preferences.assert_not_called()
        width, height = self.app._timer_size()
        self.assertGreaterEqual(width, self.app.speech.winfo_reqwidth())
        self.assertGreater(height, self.app.character_photo.height())
        self.assertLessEqual(width, self.app.root.winfo_screenwidth())
        self.assertLessEqual(height, self.app.root.winfo_screenheight())

    def test_preference_apply_and_old_preview_flags_cannot_reintroduce_metrics(self):
        candidate = replace(self.legacy, message_text_size=14)
        self.app.apply_preferences(candidate)
        self.app.display_bool_vars["show_time"].set(True)
        self.app.display_bool_vars["show_status"].set(True)
        self.app.display_bool_vars["show_message"].set(False)
        self.app._preview_widget_controls()
        self.assert_minimal_surface()
        self.assertEqual(self.app.preferences, candidate)
        self.assertEqual(self.save_preferences.call_args.args[1], candidate)

    def test_hidden_clock_still_updates_timer_and_periodic_state(self):
        engine = self.app.engine
        mono, wall = engine.last_mono, engine.last_wall
        engine.clock = lambda: mono + 2
        engine.wall = lambda: wall + 2
        engine.idle_provider = lambda: (0.0, 1)
        before_active = self.app.state.daily.active_seconds
        before_continuous = self.app.state.session.continuous_seconds
        self.app._tick_safe()
        self.assertEqual(self.app.state.daily.active_seconds, before_active + 2)
        self.assertEqual(self.app.state.session.continuous_seconds, before_continuous + 2)
        self.assert_minimal_surface()
        self.app._save_periodic()
        restored = load_state(self.data / "state.json")
        self.assertEqual(restored.daily.active_seconds, self.app.state.daily.active_seconds)
        self.assertEqual(restored.session.continuous_seconds, self.app.state.session.continuous_seconds)

    def test_manual_details_settings_and_emergency_hide_remain_available(self):
        self.app.show_stats()
        self.assertEqual(self.app.current_page, "stats")
        self.app._show_page("settings")
        self.assertEqual(self.app.current_page, "settings")
        self.app._show_page("timer")
        self.app.root.update()
        self.assert_minimal_surface()
        self.app._emergency_hide()
        self.assertEqual(self.app.root.state(), "withdrawn")
        self.app.show()
        self.app.root.update()
        self.assert_minimal_surface()


if __name__ == "__main__":
    unittest.main()
