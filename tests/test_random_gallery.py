"""Real gallery controls, using synthetic PNG fixtures and isolated app data."""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, replace
import gc
import json
import os
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import patch

from PIL import Image, ImageTk

_IMPORT_DATA = tempfile.TemporaryDirectory(prefix="seunga-random-import-")
os.environ.setdefault("APPDATA", _IMPORT_DATA.name)
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

import compact_runtime_features as runtime
from desktop_compact import CompactDesktopApp
from desktop_gallery import GalleryDesktopApp
from desktop_gallery_final import FinalGalleryDesktopApp
from settings import UserSettings
from state import fresh_state


class RandomGalleryTkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest("A display is needed for real Tk random-gallery controls")

    def setUp(self):
        gc.collect()
        self.addCleanup(self._collect_tk_cycles)
        self.directory = tempfile.TemporaryDirectory(prefix="seunga-random-gallery-")
        self.addCleanup(self.directory.cleanup)
        self.data = Path(self.directory.name)
        self.first = self.data / "fixture-red.png"
        self.second = self.data / "fixture-blue.png"
        for path, color in ((self.first, "#D43C3C"), (self.second, "#324FD0")):
            Image.new("RGBA", (600, 1000), color).save(path)
        self.preferences = UserSettings(
            ai_enabled=False, ai_remember_key=False, always_on_top=True,
            break_reminders=False, workday_reminders=False,
            builtin_image_set="01", widget_scale=100,
        )
        self.manual_file = self.data / "manual_asset_overrides.json"
        self.manual_file.write_text(json.dumps({
            "default": "builtin:default/default_01.png",
        }), encoding="utf-8")
        self.settings_file = self.data / "settings.json"
        self.settings_file.write_text(json.dumps(asdict(self.preferences)), encoding="utf-8")
        patches = (
            patch("app.DATA_DIR", self.data),
            patch("app.STATE_FILE", self.data / "state.json"),
            patch("app.SETTINGS_FILE", self.settings_file),
            patch("app.load_user_settings", return_value=self.preferences),
            patch("app.load_state", side_effect=lambda _path: fresh_state()),
            patch("app.App._start_tray"),
            patch("desktop_compact.USER_IMAGE_DIR", self.data / "images"),
            patch("desktop_compact.USER_IMAGE_SET_DIR", self.data / "image_sets"),
            patch.object(GalleryDesktopApp, "MANUAL_OVERRIDE_FILE", self.manual_file),
            patch.object(GalleryDesktopApp, "GALLERY_RANDOM_FILE", self.data / "shuffle.json"),
            patch("desktop_compact.CompactDesktopApp._start_global_hotkey"),
            patch("desktop_compact.should_suppress_overlay_notifications", return_value=False),
            patch("windows_idle.last_input_info", return_value=(0.0, 1)),
            patch("ai_desktop.HTTPClient.generate", side_effect=AssertionError("No network in gallery tests")),
        )
        for item in patches:
            item.start()
            self.addCleanup(item.stop)
        self.app = FinalGalleryDesktopApp()
        self._cancel_callbacks(self.app)
        self.app.root.update()

    @staticmethod
    def _cancel_callbacks(app):
        # Scheduled timer ticks are tested elsewhere. Freeze them so synchronous
        # image clicks can be compared without unrelated elapsed-time changes.
        for pending in app.root.tk.call("after", "info"):
            app.root.tk.call("after", "cancel", pending)

    @staticmethod
    def _close(app):
        if hasattr(app, "ai_service"):
            app._ai_closed = True
            app.ai_service.close()
        RandomGalleryTkTests._cancel_callbacks(app)
        app.root.destroy()

    def tearDown(self):
        self._close(self.app)

    def _collect_tk_cycles(self):
        self.app = None
        gc.collect()

    @contextmanager
    def candidates(self, *paths):
        with patch.object(runtime, "_gallery_candidates", return_value=list(paths)), \
             patch.object(runtime.random.SystemRandom, "shuffle", side_effect=lambda _items: None):
            yield

    def click(self, widget):
        self.app.root.update_idletasks()
        x, y = widget.winfo_width() // 2, widget.winfo_height() // 2
        widget.event_generate("<ButtonPress-1>", x=x, y=y)
        widget.event_generate("<ButtonRelease-1>", x=x, y=y)
        self.app.root.update_idletasks()

    def pixels(self):
        return ImageTk.getimage(self.app.character_photo).tobytes()

    def selection_files(self):
        return {path.relative_to(self.data).as_posix(): path.read_bytes()
                for path in self.data.rglob("*") if path.is_file()}

    def test_final_entrypoint_installs_visible_controls_and_install_is_idempotent(self):
        app = self.app
        self.assertTrue(app._random_gallery_installed)
        self.assertIs(app.random_gallery_control.master, app.hero)
        self.assertEqual(app.random_gallery_control.cget("text"), "🎲")
        self.assertTrue(app.random_gallery_control.winfo_ismapped())
        self.assertFalse(app.random_gallery_restore.winfo_ismapped())
        control = app.random_gallery_control
        setter = app._set_character
        runtime._install_random_gallery(app)
        self.assertIs(app.random_gallery_control, control)
        self.assertIs(app._set_character, setter)

    def test_legacy_compact_entrypoint_keeps_random_controls(self):
        # PIL's default Tk image master is process-global, so exercise the
        # second entrypoint after destroying the first root, as real launches do.
        self._close(self.app)
        self.app = None
        gc.collect()
        self.app = CompactDesktopApp()
        self._cancel_callbacks(self.app)
        self.app.root.update()
        self.assertTrue(self.app._random_gallery_installed)
        self.assertTrue(self.app.random_gallery_control.winfo_ismapped())
        self.assertFalse(self.app.random_gallery_restore.winfo_ismapped())

    def test_real_control_clicks_change_and_restore_without_navigation_or_drag(self):
        app = self.app
        app.character_role = None
        app._set_character("default")
        original = self.pixels()
        before_speech = app.speech.cget("text")
        with self.candidates(self.first, self.second), \
             patch.object(app, "_show_page") as navigate, \
             patch.object(app, "_open_chat") as chat, \
             patch.object(app, "_start_drag") as drag, \
             patch.object(app, "_save_window_position") as save_position:
            self.click(app.random_gallery_control)
            self.assertTrue(app._random_gallery_active)
            self.assertEqual(app._random_gallery_last_path, str(self.first))
            self.assertNotEqual(self.pixels(), original)
            self.assertTrue(app.random_gallery_restore.winfo_ismapped())
            self.click(app.random_gallery_restore)
            self.assertFalse(app._random_gallery_active)
            self.assertIsNone(app._random_gallery_last_path)
            self.assertEqual(app.character_role, "default")
            self.assertEqual(self.pixels(), original)
            self.assertFalse(app.random_gallery_restore.winfo_ismapped())
            navigate.assert_not_called()
            chat.assert_not_called()
            drag.assert_not_called()
            save_position.assert_not_called()
        self.assertEqual(app.current_page, "timer")
        self.assertIsNone(app._drag_origin)
        self.assertEqual(app.speech.cget("text"), before_speech)

    def test_multiple_candidates_avoid_immediate_repeat_and_single_candidate_still_works(self):
        with self.candidates(self.first, self.second):
            paths = []
            for _ in range(4):
                self.click(self.app.random_gallery_control)
                paths.append(self.app._random_gallery_last_path)
            self.assertEqual(paths, [str(self.first), str(self.second)] * 2)
        with self.candidates(self.first):
            self.click(self.app.random_gallery_control)
            self.click(self.app.random_gallery_control)
            self.assertTrue(self.app._random_gallery_active)
            self.assertEqual(self.app._random_gallery_last_path, str(self.first))

    def test_restore_uses_latest_timer_role_while_random_image_stays_displayed(self):
        for latest in ("default", "away", "worry"):
            with self.subTest(latest=latest), self.candidates(self.first):
                self.click(self.app.random_gallery_control)
                displayed = self.pixels()
                self.app._set_character("rest")
                self.app._set_character(latest)
                self.assertEqual(self.pixels(), displayed)
                self.assertEqual(self.app._random_gallery_state_role, latest)
                with patch.object(self.app, "_random_gallery_original_set_character",
                                  wraps=self.app._random_gallery_original_set_character) as restore:
                    self.click(self.app.random_gallery_restore)
                    restore.assert_called_once_with(latest)
                self.assertEqual(self.app.character_role, latest)
                self.assertFalse(self.app._random_gallery_active)

    def test_random_and_restore_preserve_timer_preferences_and_all_selection_files(self):
        app = self.app
        app.state.daily.active_seconds = 1234.5
        app.state.daily.away_seconds = 41.5
        app.state.session.continuous_seconds = 321.5
        app.state.session.next_break_at = 3600
        app._image_set_store.import_files("rest", [self.second])
        state = deepcopy(asdict(app.state))
        preferences = app.preferences
        overrides = dict(app._manual_asset_overrides)
        files = self.selection_files()
        engine = app.engine
        engine_clock = (engine.last_mono, engine.last_wall)
        with self.candidates(self.first, self.second), \
             patch.object(engine, "tick") as tick, \
             patch.object(app, "_save_manual_overrides") as save_override, \
             patch("app.save_user_settings") as save_app, \
             patch("desktop_compact.save_user_settings") as save_compact:
            self.click(app.random_gallery_control)
            self.click(app.random_gallery_control)
            self.click(app.random_gallery_restore)
            tick.assert_not_called()
            save_override.assert_not_called()
            save_app.assert_not_called()
            save_compact.assert_not_called()
        self.assertIs(app.engine, engine)
        self.assertIs(app.engine.state, app.state)
        self.assertEqual((engine.last_mono, engine.last_wall), engine_clock)
        self.assertEqual(asdict(app.state), state)
        self.assertEqual(app.preferences, preferences)
        self.assertEqual(app._manual_asset_overrides, overrides)
        self.assertEqual(self.selection_files(), files)

    def test_empty_and_invalid_candidates_keep_previous_display_and_selection(self):
        corrupt = self.data / "fixture-corrupt.png"
        corrupt.write_bytes(b"synthetic invalid PNG fixture")
        for active in (False, True):
            if active:
                with self.candidates(self.first):
                    self.click(self.app.random_gallery_control)
            photo = self.app.character_photo
            previous = self.app._random_gallery_last_path
            for paths in ((), (corrupt,)):
                with self.subTest(active=active, paths=paths), self.candidates(*paths), \
                     patch.object(runtime.core.log, "exception"):
                    self.click(self.app.random_gallery_control)
                    self.assertIs(self.app.character_photo, photo)
                    self.assertEqual(self.app._random_gallery_active, active)
                    self.assertEqual(self.app._random_gallery_last_path, previous)

    def test_invalid_candidate_is_skipped_when_valid_image_is_available(self):
        corrupt = self.data / "fixture-corrupt.png"
        corrupt.write_bytes(b"synthetic invalid PNG fixture")
        with self.candidates(corrupt, self.second), patch.object(runtime.core.log, "exception"):
            self.click(self.app.random_gallery_control)
        self.assertTrue(self.app._random_gallery_active)
        self.assertEqual(self.app._random_gallery_last_path, str(self.second))

    def test_controls_remain_visible_above_long_bubble_at_supported_scales(self):
        app = self.app
        # Keep this control-spacing test within the physical Windows work area.
        # Large artwork scaling and rerendering are exercised separately below.
        spacing_image = self.data / "fixture-spacing.png"
        Image.new("RGBA", (120, 180), "#D43C3C").save(spacing_image)
        app.speech.configure(text="긴 말풍선이 있어도 랜덤 이미지 버튼을 누를 수 있어야 해요. " * 3)
        for scale in (80, 100, 140, 200):
            with self.subTest(scale=scale), self.candidates(spacing_image):
                app.preferences = replace(app.preferences, widget_scale=scale)
                app.widget_scale_var.set(scale)
                app._apply_widget_appearance()
                app._resize_for_page("timer")
                self.click(app.random_gallery_control)
                app.root.update()
                bubble_top = app.speech.winfo_rooty()
                character_top = app.character.winfo_rooty()
                for control in (app.random_gallery_control, app.random_gallery_restore):
                    self.assertTrue(control.winfo_ismapped())
                    left, top = control.winfo_rootx(), control.winfo_rooty()
                    right = left + control.winfo_width()
                    bottom = top + control.winfo_height()
                    self.assertGreaterEqual(left, app.root.winfo_rootx())
                    self.assertLessEqual(right, app.root.winfo_rootx() + app.root.winfo_width())
                    self.assertGreaterEqual(top, app.root.winfo_rooty())
                    self.assertLessEqual(bottom, bubble_top)
                    self.assertLessEqual(bottom, character_top)
                    # Windows' transparent colour key lets empty label padding
                    # pass through. At least one painted glyph pixel must hit the
                    # actual control; a fixed blank corner is not a click target.
                    self.assertTrue(any(
                        app.root.winfo_containing(x, y) is control
                        for y in range(top + 1, bottom - 1)
                        for x in range(left + 1, right - 1)
                    ), f"No clickable glyph point for {control.cget('text')!r} at {scale}%")

    def test_explicit_current_role_selection_cancels_random_and_shows_manual_image(self):
        app = self.app
        app.character_role = None
        app._set_character("default")
        with self.candidates(self.first):
            self.click(app.random_gallery_control)
        # The runtime can transition while its normal image is temporarily hidden.
        app._set_character("away")
        with patch.object(app.engine, "tick") as tick:
            app._apply_gallery_path("away", self.second)
            tick.assert_not_called()
        app.root.update_idletasks()
        self.assertFalse(app._random_gallery_active)
        self.assertEqual(app.character_role, "away")
        self.assertTrue(app._manual_override_path("away").samefile(self.second))
        self.assertEqual(ImageTk.getimage(app.character_photo).getpixel((0, 0))[:3], (50, 79, 208))
        self.assertFalse(app.random_gallery_restore.winfo_ismapped())
        self.assertEqual(json.loads(self.manual_file.read_text(encoding="utf-8"))["away"],
                         app._encode_asset_ref(self.second))

    def test_setting_another_role_does_not_cancel_current_random_preview(self):
        app = self.app
        app.character_role = None
        app._set_character("default")
        with self.candidates(self.first):
            self.click(app.random_gallery_control)
        app._set_character("away")
        displayed = self.pixels()
        app._apply_gallery_path("cheer", self.second)
        self.assertTrue(app._random_gallery_active)
        self.assertEqual(app._random_gallery_state_role, "away")
        self.assertEqual(self.pixels(), displayed)
        self.assertTrue(app._manual_override_path("cheer").samefile(self.second))

    def test_scale_apply_and_preview_keep_path_and_latest_role_without_redecoding_each_refresh(self):
        app = self.app
        with self.candidates(self.first):
            self.click(app.random_gallery_control)
        app._set_character("away")
        previous_size = (app.character_photo.width(), app.character_photo.height())
        real_open = Image.open
        with patch.object(runtime.Image, "open", wraps=real_open) as image_open, \
             patch.object(runtime, "_render_gallery_image", wraps=runtime._render_gallery_image) as render:
            app.widget_scale_var.set(140)
            app.apply_preferences(replace(app.preferences, widget_scale=140))
            self.assertTrue(app._random_gallery_active)
            self.assertEqual(app._random_gallery_last_path, str(self.first))
            self.assertEqual(app._random_gallery_state_role, "away")
            self.assertNotEqual((app.character_photo.width(), app.character_photo.height()), previous_size)
            selected_opens = [call for call in image_open.call_args_list
                              if call.args and call.args[0] == self.first]
            self.assertEqual(len(selected_opens), 1)
            render.assert_called_once_with(app, self.first)
            photo = app.character_photo
            for _ in range(3):
                app._preview_widget_controls()
                app._apply_widget_appearance()
                app._update_ui()
            self.assertEqual(render.call_count, 1)
            self.assertEqual(len([call for call in image_open.call_args_list
                                  if call.args and call.args[0] == self.first]), 1)
            self.assertIs(app.character_photo, photo)
            self.assertEqual(app._random_gallery_last_path, str(self.first))
            self.assertEqual(app._random_gallery_state_role, "away")
        self.click(app.random_gallery_restore)
        self.assertEqual(app.character_role, "away")

    def test_explicit_global_set_change_cancels_random_and_keeps_manual_overrides(self):
        app = self.app
        with self.candidates(self.first):
            self.click(app.random_gallery_control)
        app._set_character("away")
        overrides = dict(app._manual_asset_overrides)
        with patch.object(app.engine, "tick") as tick:
            app.apply_preferences(replace(app.preferences, builtin_image_set="02"))
            tick.assert_not_called()
        app.root.update_idletasks()
        self.assertFalse(app._random_gallery_active)
        self.assertIsNone(app._random_gallery_last_path)
        self.assertEqual(app.preferences.builtin_image_set, "02")
        self.assertEqual(app.character_role, "away")
        self.assertEqual(app._manual_asset_overrides, overrides)
        self.assertFalse(app.random_gallery_restore.winfo_ismapped())

    def test_follow_current_role_set_cancels_random_and_removes_only_that_manual_choice(self):
        app = self.app
        app._apply_gallery_path("away", self.second)
        app.character_role = None
        app._set_character("away")
        with self.candidates(self.first):
            self.click(app.random_gallery_control)
        with patch.object(app.engine, "tick") as tick:
            app._follow_selected_set("away")
            tick.assert_not_called()
        app.root.update_idletasks()
        self.assertFalse(app._random_gallery_active)
        self.assertEqual(app.character_role, "away")
        self.assertNotIn("away", app._manual_asset_overrides)
        self.assertEqual(app._manual_asset_overrides["default"], "builtin:default/default_01.png")
        self.assertFalse(app.random_gallery_restore.winfo_ismapped())


if __name__ == "__main__":
    unittest.main()
