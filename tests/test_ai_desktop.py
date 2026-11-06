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
        self.reply = SimpleNamespace(text="잘 왔어. 오늘도 옆에서 응원할게.", error_code="")

    def generate(self, _key, **_kwargs):
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        return self.reply


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
        presentation = patch("desktop_compact.should_suppress_overlay_notifications", return_value=False)
        presentation.start()
        self.addCleanup(presentation.stop)
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

    def send(self, text="안녕"):
        self.app._chat_entry.insert(0, text)
        self.app._send_chat()

    def test_disabled_chat_immediately_uses_local_reply_without_touching_timer(self):
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=False))
        self.app._open_chat()
        before = (self.app.state.daily.active_seconds, self.app.state.session.continuous_seconds,
                  self.app.state.session.is_away)
        self.app._chat_entry.insert(0, "고마워")
        self.app._send_chat()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")
        self.assertEqual(self.client.calls, 0)
        self.assertEqual(before, (self.app.state.daily.active_seconds,
                         self.app.state.session.continuous_seconds, self.app.state.session.is_away))

    def test_delayed_ai_does_not_block_tick_and_stale_return_is_discarded(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "안녕")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 대기 중")
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
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 안내")
        self.assertIsNone(self.app._chat_pending)

    def test_AI_send_waits_without_local_dialogue_or_changing_main_speech(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.app.last_dialogue_at = time.monotonic() - 65
        self.app.last_work_mode = self.app._current_workday_state().mode
        with patch("ai_desktop.local_chat_reply") as local_reply, \
             patch.object(self.service, "note_local", wraps=self.service.note_local) as note_local:
            self.send()
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            self.assertEqual(self.app._chat_messages[-1][0], "승아 · 대기 중")
            self.assertIn("기다리고", self.app._chat_ai_note)
            local_reply.assert_not_called()
            note_local.assert_not_called()
            with patch.object(self.app, "_say") as say:
                self.app._update_dialogue()
                say.assert_not_called()
            self.assertEqual(self.app.speech.cget("text"), before)

    def test_transport_error_only_then_shows_local_fallback(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.client.reply = SimpleNamespace(text="", error_code="connection_error")
        with patch("ai_desktop.local_chat_reply", return_value="연결이 없어도 잠깐 쉬어가자.") as local_reply, \
             patch.object(self.service, "note_local", wraps=self.service.note_local) as note_local:
            self.send("조금 피곤해")
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            local_reply.assert_not_called()
            note_local.assert_not_called()
            self.client.release.set()
            self.flush()
            local_reply.assert_called_once_with("조금 피곤해", self.app.preferences.personality)
            note_local.assert_called_once_with("연결이 없어도 잠깐 쉬어가자.")
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1], ("승아 · 로컬", "연결이 없어도 잠깐 쉬어가자."))
        self.assertEqual(self.app.speech.cget("text"), "연결이 없어도 잠깐 쉬어가자.")

    def test_UI_deadline_falls_back_when_backend_drops_response_and_ignores_late_reply(self):
        self.enable()
        self.app._open_chat()
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        pending = self.app._chat_pending
        with patch("ai_desktop.time", SimpleNamespace(monotonic=lambda: pending.deadline + .01)), \
             patch.object(self.service, "poll", return_value=[]), \
             patch("ai_desktop.local_chat_reply", return_value="조금 늦네. 천천히 쉬어가자."):
            self.app._ai_poll()
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")
        self.assertIn("초과", self.app._chat_ai_note)
        fallback = self.app.speech.cget("text")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), fallback)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")

    def test_repeated_send_retains_first_request_and_new_input(self):
        self.enable()
        self.app._open_chat()
        self.send("처음 말")
        self.assertTrue(self.client.started.wait(.5))
        pending = self.app._chat_pending
        generation = self.service._generation
        before = self.app.speech.cget("text")
        self.send("다음 말")
        self.assertIs(self.app._chat_pending, pending)
        self.assertEqual(self.service._generation, generation)
        self.assertEqual(self.app._chat_entry.get(), "다음 말")
        self.assertEqual(len(self.app._chat_messages), 2)
        self.assertEqual(self.app.speech.cget("text"), before)
        self.assertEqual(self.client.calls, 1)
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")

    def test_busy_or_cooldown_keeps_input_and_never_invents_local_response(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        with patch.object(self.service, "request", return_value=False), \
             patch("ai_desktop.local_chat_reply") as local_reply, \
             patch.object(self.service, "note_local") as note_local:
            self.send("잠시 대화할까")
        local_reply.assert_not_called()
        note_local.assert_not_called()
        self.assertEqual(self.app._chat_entry.get(), "잠시 대화할까")
        self.assertEqual(self.app.speech.cget("text"), before)
        self.assertFalse(self.app._chat_messages)
        self.assertIsNone(self.app._chat_pending)
        self.assertIn("잠시 후", self.app._chat_ai_note)

    def test_daily_close_also_waits_and_only_uses_fallback_after_error(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.client.reply = SimpleNamespace(text="", error_code="timeout")
        with patch("ai_desktop.pick", return_value="오늘은 여기까지. 편하게 마무리하자.") as pick:
            self.app._daily_close()
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            pick.assert_not_called()
            self.client.release.set()
            self.flush()
            pick.assert_called_once_with("leave", personality=self.app.preferences.personality)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")

    def test_clear_chat_discards_pending_and_late_result_without_speech_change(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        self.app._clear_chat()
        self.assertIsNone(self.app._chat_pending)
        self.client.release.set()
        self.flush()
        self.assertFalse(self.app._chat_messages)
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_personality_change_cancels_pending_without_fallback(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        personality = "strict" if self.app.preferences.personality != "strict" else "warm"
        self.app.apply_preferences(replace(self.app.preferences, personality=personality))
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 안내")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_explicit_chat_completes_even_when_overlay_notifications_are_suppressed(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        with patch.object(self.app, "_break_notifications_suppressed", return_value=True):
            self.flush()
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_chat_is_always_topmost_on_create_refresh_reopen_and_preferences(self):
        self.app.apply_preferences(replace(self.app.preferences, always_on_top=False))
        # Chat must also handle an old false preference still held in memory;
        # applying current preferences normalizes the timer's setting to true.
        self.app.preferences = replace(self.app.preferences, always_on_top=False)
        original_attributes = __import__("tkinter").Toplevel.attributes
        calls = []
        def attributes(window, *args):
            calls.append((window, args))
            return original_attributes(window, *args)
        with patch("ai_desktop.tk.Toplevel.attributes", autospec=True, side_effect=attributes):
            self.app._open_chat()
            window = self.app._chat_window
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            self.app._refresh_chat()
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            window.withdraw()
            self.app._open_chat()
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            self.app.apply_preferences(replace(self.app.preferences, always_on_top=False))
            self.assertIn((window, ("-topmost", True)), calls)
            self.assertTrue(self.app.preferences.always_on_top)
        self.assertEqual(window.title(), "승아와 대화")

    def test_ZIP_import_reports_automatic_number_for_complete_role_only_pack(self):
        self.assertIn("번호 없이", self.app._pack_status.cget("text"))
        result = SimpleNamespace(sets=("06",), added=10, identical=0, auto_assigned=("06",), reused=())
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-role-only.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("06번을 자동 배정", message)
        self.assertIn("10장 추가", message)
        self.assertNotIn("기존 06번", message)

    def test_ZIP_import_reports_reused_existing_number_without_claiming_new_images(self):
        result = SimpleNamespace(sets=("03",), added=0, identical=10, auto_assigned=(), reused=("03",))
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-repeat.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("기존 03번을 그대로 사용", message)
        self.assertIn("0장 추가", message)
        self.assertIn("동일 파일 10장 유지", message)
        self.assertNotIn("자동 배정", message)
        self.assertNotIn("앱을 다시 열면", message)

    def test_ZIP_import_reports_merged_incoming_groups_without_claiming_installed_number(self):
        result = SimpleNamespace(sets=("22",), added=10, identical=0, auto_assigned=(), reused=("22",))
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-merged.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("동일한 내용의 세트는 22번으로 합쳤습니다", message)
        self.assertIn("10장 추가", message)
        self.assertNotIn("기존 22번", message)
        self.assertNotIn("자동 배정", message)

    def test_current_ai_reply_appears_and_key_never_enters_settings(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "다녀왔어")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")
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
