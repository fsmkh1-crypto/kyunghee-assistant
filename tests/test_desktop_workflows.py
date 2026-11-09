from contextlib import contextmanager
from dataclasses import asdict
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch


@unittest.skipUnless(
    sys.platform == "win32" or os.environ.get("SEUNGA_TK_TEST_DISPLAY") == "1",
    "Requires a Windows desktop or an explicit Tk test display",
)
class DesktopWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Importing the desktop initializes its log path; isolate that too.
        directory = cls.enterClassContext(TemporaryDirectory())
        cls.enterClassContext(patch.dict(os.environ, {"APPDATA": directory, "PYSTRAY_BACKEND": "dummy"}))
        import app

        def close_owned_logs():
            for handler in list(app.log.handlers):
                filename = getattr(handler, "baseFilename", "")
                if filename and Path(filename).is_relative_to(Path(directory)):
                    app.log.removeHandler(handler)
                    handler.close()

        cls.addClassCleanup(close_owned_logs)

    @contextmanager
    def desktop(self, *, dpi=96):
        import tkinter as tk
        import app
        import desktop_compact as compact
        from desktop_gallery_final import FinalGalleryDesktopApp
        from settings import UserSettings, save_user_settings

        with TemporaryDirectory() as directory:
            data = Path(directory)
            settings_file = data / "settings.json"
            save_user_settings(settings_file, UserSettings(
                welcome_seen=True, builtin_image_set="01", widget_scale=100,
                custom_dialogue="기존 대사", window_x=30, window_y=30,
            ))
            real_tk = tk.Tk

            def create_root():
                root = real_tk()
                root.tk.call("tk", "scaling", dpi / 72)
                return root

            with (
                patch.multiple(app, DATA_DIR=data, SETTINGS_FILE=settings_file, STATE_FILE=data / "state.json"),
                patch.multiple(compact, USER_IMAGE_DIR=data / "images", USER_IMAGE_SET_DIR=data / "image_sets"),
                patch.object(app.App, "_start_tray"),
                patch.object(compact.CompactDesktopApp, "_start_global_hotkey"),
                patch.object(FinalGalleryDesktopApp, "MANUAL_OVERRIDE_FILE", data / "manual.json"),
                patch.object(tk, "Tk", create_root),
            ):
                desktop = FinalGalleryDesktopApp()
                try:
                    # Keep these interaction tests deterministic: timer scheduling has its own suite.
                    self.cancel_callbacks(desktop.root)
                    desktop.root.update()
                    yield desktop
                finally:
                    desktop._hotkey_stop.set()
                    desktop._assistant_shutdown.set()
                    if desktop._assistant_windows is not None:
                        desktop._assistant_windows.close()
                    self.cancel_callbacks(desktop.root)
                    desktop.root.destroy()

    @staticmethod
    def cancel_callbacks(root):
        for event_id in root.tk.splitlist(root.tk.call("after", "info")):
            root.tk.call("after", "cancel", event_id)

    @staticmethod
    def descendants(widget):
        for child in widget.winfo_children():
            yield child
            yield from DesktopWorkflowTests.descendants(child)

    def button(self, root, text):
        matches = [widget for widget in self.descendants(root)
                   if widget.winfo_class() in {"Button", "TButton"} and widget.cget("text") == text]
        self.assertEqual(len(matches), 1, f"Expected one button: {text}")
        return matches[0]

    def assert_visible_inside(self, widget, parent):
        self.assertTrue(widget.winfo_viewable())
        x = widget.winfo_rootx() - parent.winfo_rootx()
        y = widget.winfo_rooty() - parent.winfo_rooty()
        self.assertGreaterEqual(x, 0)
        self.assertGreaterEqual(y, 0)
        self.assertLessEqual(x + widget.winfo_width(), parent.winfo_width())
        self.assertLessEqual(y + widget.winfo_height(), parent.winfo_height())
        self.assertGreaterEqual(widget.winfo_width(), widget.winfo_reqwidth())
        self.assertGreaterEqual(widget.winfo_height(), widget.winfo_reqheight())

    def test_settings_footer_actions_remain_visible_on_every_tab_at_common_dpi(self):
        for dpi in (96, 120, 144, 192):
            with self.subTest(dpi=dpi), self.desktop(dpi=dpi) as desktop:
                desktop._show_page("settings")
                for tab in desktop._settings_notebook.tabs():
                    desktop._settings_notebook.select(tab)
                    desktop.root.update()
                    canvas = desktop._settings_canvases[tab]
                    for position in (0, 1):
                        canvas.yview_moveto(position)
                        desktop.root.update()
                        self.assert_visible_inside(self.button(desktop.settings_page, "설정 저장"), desktop.root)
                        self.assert_visible_inside(self.button(desktop.settings_page, "미저장 변경 버리기"), desktop.root)

    def test_away_state_and_pose_survive_settings_preview_and_return(self):
        with self.desktop() as desktop:
            desktop.engine.start_manual_away()
            desktop._set_character("away")
            before = asdict(desktop.state)
            desktop._show_page("settings")
            desktop.widget_scale_var.set(140)
            desktop._preview_widget_controls()
            desktop._show_page("timer")
            desktop.root.update()
            self.assertEqual(asdict(desktop.state), before)
            self.assertEqual(desktop.character_role, "away")

    @staticmethod
    def fake_timer(desktop):
        from state import fresh_state
        from timer_engine import TimerEngine
        desktop.state = fresh_state()
        env = SimpleNamespace(mono=0.0, wall=1000.0, idle=0.0, input_tick=1)
        desktop.engine = TimerEngine(desktop.state, clock=lambda: env.mono, wall=lambda: env.wall,
                                     idle_provider=lambda: (env.idle, env.input_tick))
        return env

    def test_manual_away_clock_advances_without_inflating_saved_stats_and_returns_to_focus(self):
        import app
        from state import load_state, save_state
        from timer_engine import MANUAL_INPUT_GRACE_SEC
        with self.desktop() as desktop:
            env = self.fake_timer(desktop)
            desktop.state.daily.away_seconds = desktop.state.daily.manual_away_seconds = 120
            desktop.engine.start_manual_away()
            for second in range(1, 4):
                env.mono = second
                env.wall = 1000 + second
                env.idle = second
                desktop.engine.tick()
                before = asdict(desktop.state)
                desktop._update_ui()
                desktop._update_ui()
                self.assertEqual(asdict(desktop.state), before)
                self.assertEqual(desktop.cont.cget("text"), f"00:00:0{second}")
                self.assertEqual(desktop.detail_cont.cget("text"), desktop.cont.cget("text"))
                self.assertEqual(desktop.main_status.cget("text"), "자리비움 중")
                self.assertEqual(desktop.state.daily.manual_away_seconds, 120 + second)
                self.assertEqual(desktop.state.session.continuous_seconds, 0)
            save_state(app.STATE_FILE, desktop.state, now_wall=env.wall)
            restored = load_state(app.STATE_FILE)
            self.assertEqual(restored.daily.away_seconds, 123)
            self.assertEqual(restored.daily.manual_away_seconds, 123)
            env.mono = MANUAL_INPUT_GRACE_SEC + 1
            env.wall = 1000 + env.mono
            env.input_tick += 1
            env.idle = 0
            self.assertTrue(desktop.engine.tick().became_active)
            desktop._update_ui()
            self.assertEqual(desktop.cont.cget("text"), "00:00:00")
            self.assertEqual(desktop.main_status.cget("text"), "집중 중")
            env.mono += 2
            env.wall += 2
            env.input_tick += 1
            desktop.engine.tick()
            desktop._update_ui()
            self.assertEqual(desktop.cont.cget("text"), "00:00:02")
            self.assertEqual(desktop.state.daily.manual_away_seconds, 120 + MANUAL_INPUT_GRACE_SEC + 1)

    def test_auto_away_clock_starts_from_reclassified_idle_duration(self):
        from timer_engine import IDLE_THRESHOLD_SEC
        with self.desktop() as desktop:
            env = self.fake_timer(desktop)
            for second in range(1, IDLE_THRESHOLD_SEC + 2):
                env.mono = second
                env.wall = 1000 + second
                env.idle = second
                desktop.engine.tick()
                if second >= IDLE_THRESHOLD_SEC:
                    desktop._update_ui()
                    self.assertEqual(desktop.cont.cget("text"), f"00:05:0{second - IDLE_THRESHOLD_SEC}")
                    self.assertEqual(desktop.detail_cont.cget("text"), desktop.cont.cget("text"))
                    self.assertEqual(desktop.main_status.cget("text"), "자리비움 중")
                    self.assertEqual(desktop.state.daily.auto_away_seconds, second)
                    self.assertEqual(desktop.state.daily.active_seconds, 0)

    def test_unsaved_drafts_survive_page_navigation_and_discard_restores_fields(self):
        with self.desktop() as desktop:
            desktop._show_page("settings")
            desktop.break_interval_var.set("75")
            desktop.custom_dialogue_text.delete("1.0", "end")
            desktop.custom_dialogue_text.insert("1.0", "작성 중인 대사")
            desktop._show_page("timer")
            desktop._show_page("settings")
            self.assertEqual(desktop.break_interval_var.get(), "75")
            self.assertEqual(desktop.custom_dialogue_text.get("1.0", "end-1c"), "작성 중인 대사")
            self.assertEqual(desktop.settings_dirty_label.cget("text"), "저장 안 됨")
            desktop._discard_settings()
            self.assertEqual(desktop.break_interval_var.get(), "60")
            self.assertEqual(desktop.custom_dialogue_text.get("1.0", "end-1c"), "기존 대사")
            self.assertEqual(desktop.settings_dirty_label.cget("text"), "저장됨")

    def test_saving_preserves_welcome_and_unedited_preferences(self):
        import app
        from settings import load_user_settings
        with self.desktop() as desktop:
            before = asdict(desktop.preferences)
            desktop._show_page("settings")
            desktop.break_interval_var.set("75")
            self.assertTrue(desktop._save_settings())
            saved = asdict(load_user_settings(app.SETTINGS_FILE))
            for field in ("welcome_seen", "window_x", "window_y", "custom_dialogue", "builtin_image_set"):
                self.assertEqual(saved[field], before[field])
            self.assertEqual(saved["break_interval_minutes"], 75)
            self.assertEqual(desktop.settings_dirty_label.cget("text"), "저장됨")

    def test_welcome_completion_preserves_existing_preferences(self):
        import app
        from settings import load_user_settings
        with self.desktop() as desktop:
            before = asdict(desktop.preferences)
            desktop._show_welcome()
            desktop.root.update()
            self.button(desktop.root, "AI 없이 시작").invoke()
            self.assertEqual(asdict(load_user_settings(app.SETTINGS_FILE)), before)

    def test_mousewheel_in_other_window_does_not_scroll_settings(self):
        import tkinter as tk
        with self.desktop() as desktop:
            desktop._show_page("settings")
            desktop._settings_notebook.select(2)
            desktop.root.update()
            canvas = desktop._settings_canvases[desktop._settings_notebook.select()]
            window = tk.Toplevel(desktop.root)
            text = tk.Text(window)
            text.pack()
            window.update()
            # The image tab can fit without overflow after its simplification.
            # Give this actual scroll surface a longer document for wheel isolation.
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), canvas.winfo_height() * 3))
            canvas.yview_moveto(0.25)
            before = canvas.yview()
            desktop._settings_mousewheel(SimpleNamespace(widget=text, delta=-120))
            self.assertEqual(canvas.yview(), before)
            desktop._settings_mousewheel(SimpleNamespace(widget=canvas, delta=-120))
            self.assertNotEqual(canvas.yview(), before)
            window.destroy()

    def test_failed_settings_write_rolls_back_image_manifest_and_preferences(self):
        import app
        with self.desktop() as desktop:
            desktop._image_set_store.set_options("away", fit_mode="fit", alignment="top")
            manifest = desktop._image_set_store._load_manifest()
            preferences = desktop.preferences
            desktop._show_page("settings")
            desktop.image_mode_vars["away"].set("가운데 크롭")
            desktop.image_alignment_vars["away"].set("아래")
            desktop.break_interval_var.set("75")
            with patch.object(app, "save_user_settings", side_effect=OSError("simulated settings disk error")):
                self.assertFalse(desktop._save_settings())
            self.assertEqual(desktop._image_set_store._load_manifest(), manifest)
            self.assertEqual(desktop.preferences, preferences)
            self.assertEqual(desktop.break_interval_var.get(), "75")
            self.assertEqual(desktop.settings_dirty_label.cget("text"), "저장 안 됨")


if __name__ == "__main__":
    unittest.main()
