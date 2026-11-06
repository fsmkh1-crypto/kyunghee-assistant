"""Integration with the real gallery shell, using only isolated data and fake HTTP."""
from dataclasses import replace
from datetime import datetime
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

# app.py creates its log directory on import. Keep test runs out of real app data.
_DATA = tempfile.TemporaryDirectory(prefix="kyunghee-ai-ui-tests-")
os.environ["APPDATA"] = _DATA.name
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

from ai_desktop import local_chat_reply, timer_context
from ai_dialogue import AIService
from desktop_gallery_final import FinalGalleryDesktopApp
from state import fresh_state


class ContextTests(unittest.TestCase):
    def test_snapshot_contains_only_requested_day_facts(self):
        state = fresh_state()
        state.daily.active_seconds = 3661
        state.session.continuous_seconds = 120
        result = timer_context(state, "wind_down", "warm", datetime(2026, 11, 6, 17, 15),
                               recent_break_minutes=5, api_key="DO-NOT-SEND", path="private")
        self.assertEqual(result["local_time"], "17:15")
        self.assertEqual(result["active_minutes"], 61)
        self.assertEqual(result["continuous_minutes"], 2)
        self.assertEqual(result["recent_break_minutes"], 5)
        self.assertEqual(result["workday_stage"], "wind_down")
        self.assertNotIn("api_key", result)
        self.assertNotIn("path", result)
        night = timer_context(state, "normal", "balanced", datetime(2026, 11, 6, 1, 0))
        self.assertEqual(night["time_of_day"], "late")

    def test_local_chat_uses_existing_personality_dialogue(self):
        with patch("ai_desktop.pick", return_value="기존 대사") as pick:
            self.assertEqual(local_chat_reply("조금 피곤해", "warm"), "기존 대사")
            pick.assert_called_once_with("break", personality="warm")


class BlockingClient:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0

    def generate(self, _key, **_kwargs):
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        return SimpleNamespace(text="잘 왔어. 오늘도 옆에서 응원할게.", error_code="")


class GalleryAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest("A display is needed for the real Tk gallery integration")

    def setUp(self):
        self.client = BlockingClient()
        self.service = AIService(self.client, cooldown_seconds=0, chat_cooldown_seconds=0)
        with patch("ai_desktop.AIService", return_value=self.service), \
             patch("app.App._start_tray"), \
             patch("desktop_compact.CompactDesktopApp._start_global_hotkey"):
            self.app = FinalGalleryDesktopApp()
        self.app.root.update()

    def tearDown(self):
        self.client.release.set()
        self.app._ai_closed = True
        self.service.close()
        for pending in self.app.root.tk.call("after", "info"):
            # Tcl cancellation leaves each child widget's registered command
            # for that widget to delete during destruction.
            self.app.root.tk.call("after", "cancel", pending)
        self.app.root.destroy()
        if self.service._worker:
            self.service._worker.join(timeout=1)

    def enable(self):
        self.app.ai_credentials.configure_key("test-key-no-network", False)
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=True,
                                          ai_remember_key=False))

    def flush(self):
        deadline = time.monotonic() + 1
        while self.service._in_flight is not None and time.monotonic() < deadline:
            self.app._ai_poll()
            self.app.root.update_idletasks()
            time.sleep(.002)

    def test_disabled_chat_immediately_uses_local_reply_without_touching_timer(self):
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=False))
        self.app._open_chat()
        before = (self.app.state.daily.active_seconds, self.app.state.session.continuous_seconds,
                  self.app.state.session.is_away)
        self.app._chat_entry.insert(0, "고마워")
        self.app._send_chat()
        self.assertEqual(self.app._chat_messages[-1][0], "경희 · 로컬")
        self.assertEqual(self.client.calls, 0)
        self.assertEqual(before, (self.app.state.daily.active_seconds,
                         self.app.state.session.continuous_seconds, self.app.state.session.is_away))

    def test_delayed_ai_does_not_block_tick_and_stale_return_is_discarded(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "안녕")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.assertEqual(self.app._chat_messages[-1][0], "경희 · 로컬")
        engine = self.app.engine
        current = engine.last_mono
        engine.clock = lambda: current + 2
        engine.wall = lambda: engine.last_wall + 2
        engine.idle_provider = lambda: (0.0, 1)
        active_before = self.app.state.daily.active_seconds
        self.app._tick_safe()
        self.assertGreater(self.app.state.daily.active_seconds, active_before)
        self.app.toggle_manual_away()
        away_line = self.app.speech.cget("text")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), away_line)
        self.assertEqual(self.app._chat_messages[-1][0], "경희 · 로컬")

    def test_current_ai_reply_appears_and_key_never_enters_settings(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "다녀왔어")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "경희 · AI")
        self.assertEqual(self.app.speech.cget("text"), "잘 왔어. 오늘도 옆에서 응원할게.")
        from app import SETTINGS_FILE
        saved = SETTINGS_FILE.read_text(encoding="utf-8")
        self.assertNotIn("test-key-no-network", saved)
        self.assertNotIn("api_key", saved)
        self.app._save_settings()
        self.assertTrue(self.app.preferences.ai_enabled)
        self.app._clear_chat()
        self.assertFalse(self.app._chat_messages)

    def test_clearing_key_and_turning_off_stop_runtime_even_when_settings_write_fails(self):
        self.enable()
        self.assertTrue(self.service._enabled)
        self.app.ai_credentials.clear()
        with patch("app.save_user_settings", side_effect=OSError("read-only settings")):
            with self.assertRaises(OSError):
                self.app._apply_ai_settings(True, False, "")
        self.assertFalse(self.service._enabled)
        self.assertEqual(self.service._api_key, "")
        self.enable()
        with patch("app.save_user_settings", side_effect=OSError("read-only settings")):
            with self.assertRaises(OSError):
                self.app._apply_ai_settings(False, False, self.app.ai_credentials.api_key)
        self.assertFalse(self.service._enabled)
        self.assertFalse(self.app.preferences.ai_enabled)


if __name__ == "__main__":
    unittest.main()
