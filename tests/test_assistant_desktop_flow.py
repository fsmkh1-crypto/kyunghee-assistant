"""Exercise the real mixin without opening Tk windows or contacting an API."""
from collections import deque
import importlib.util
import os
from pathlib import Path
import queue
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(importlib.util.find_spec("pystray"), "Desktop dependencies not installed")
class DesktopAssistantFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        with patch.dict(os.environ, {"APPDATA": cls.directory.name, "PYSTRAY_BACKEND": "dummy"}):
            from assistant_ai.desktop import DesktopAssistantMixin
        class LocalTimer:
            def _update_dialogue(self):
                self.local_calls.append("periodic")
                self.last_dialogue_at = 100
            def _cycle_message(self, event=None):
                self.local_calls.append("manual")
            def _set_character(self, role):
                self.character_role = role
            def _visible_speech(self):
                return self.speech
            def _say(self, kind, text=None, work_mode="normal"):
                self.speech.configure(text=text)
                self.last_dialogue_at = 100
        class Desktop(DesktopAssistantMixin, LocalTimer):
            pass
        cls.desktop_type = Desktop

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def setUp(self):
        self.app = app = self.desktop_type.__new__(self.desktop_type)
        app.local_calls = []
        app.last_dialogue_at = 0
        app.last_work_mode = "normal"
        app._assistant_periodic_due = False
        app._assistant_pending = None
        app._assistant_shutdown = threading.Event()
        app._assistant_events = deque(maxlen=40)
        app._assistant_recent_dialogue = deque(maxlen=12)
        app._assistant_last_attempt = app._assistant_last_periodic = float("-inf")
        app._assistant_last_chat_at = float("-inf")
        app._assistant_local_rotation = 0
        app._assistant_windows = None
        app._chat_phase = "idle"
        app._last_chat_reply = ""
        app._expandable_reply = ""
        app._chat_expiry = None
        app._timer_character_role = "default"
        app._chat_button, app._chat_speech = Mock(), Mock()
        app._chat_speech.wrapped_lines.side_effect = lambda text, limit: text.splitlines()
        app.current_page = "timer"
        app.preferences = SimpleNamespace(show_message=True)
        app.root, app.speech = Mock(), Mock()
        app._apply_widget_appearance = Mock()
        app._refresh_chat_layout = Mock()
        app._open_assistant_chat = Mock()
        app._break_notifications_suppressed = lambda: False
        app.ui_commands = queue.Queue()
        app._assistant_tools = SimpleNamespace(context=lambda: {
            "date": "2026-11-09", "is_away": False, "workday_mode": "normal", "break_reminders_enabled_today": True,
        })
        app._assistant_service = Mock()
        app._assistant_service.revision = 0
        app._assistant_service.can_proactively_speak.return_value = True
        app._assistant_service.load_settings.return_value = SimpleNamespace(proactive_interval_minutes=20)

    def test_local_dialogue_is_displayed_before_network_and_survives_failure(self):
        app = self.app
        entered, release = threading.Event(), threading.Event()
        def pending(*args, **kwargs):
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test did not release worker")
            raise OSError("fake network timeout")
        app._assistant_service.proactive.side_effect = pending
        app._update_dialogue()
        self.assertEqual(app.local_calls, ["periodic"])
        self.assertTrue(app._assistant_periodic_due)
        app._request_proactive("periodic")
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(app.local_calls, ["periodic"])
        finally:
            release.set()
        app.ui_commands.get(timeout=3)()
        self.assertEqual(app.local_calls, ["periodic"])
        app.speech.configure.assert_not_called()

    def test_new_conversation_discards_late_proactive_reply(self):
        app = self.app
        app._assistant_service.proactive.return_value = "늦은 응원"
        app._request_proactive("return")
        finish = app.ui_commands.get(timeout=3)
        app._cancel_proactive()
        finish()
        app.speech.configure.assert_not_called()
        self.assertEqual(app._assistant_events[-1]["event"], "return")

    def test_speech_click_always_opens_chat_instead_of_rotating_lines(self):
        for enabled in (False, True):
            self.app._assistant_service.can_proactively_speak.return_value = enabled
            self.app._cycle_message()
        self.assertEqual(self.app._open_assistant_chat.call_count, 2)
        self.assertEqual(self.app.local_calls, [])

    def test_reply_survives_hide_and_draft_then_clears_for_new_send(self):
        app = self.app
        app._show_chat_phase("reply", "직접 받은 답변")
        app._show_chat_phase("idle")  # Closing the chat window.
        self.assertEqual(app._chat_phase, "reply")
        app._chat_speech.configure.assert_called_with(text="직접 받은 답변")
        self.assertIs(app._visible_speech(), app._chat_speech)
        app.root.after.assert_not_called()  # Replies no longer silently expire.
        app._show_chat_phase("composing")
        app._show_chat_phase("idle")
        app._chat_speech.configure.assert_called_with(text="직접 받은 답변")
        app._show_chat_phase("waiting")
        app._show_chat_phase("idle")  # Cancelling a new send must not revive it.
        self.assertEqual((app._chat_phase, app._last_chat_reply), ("idle", ""))

    def test_explicit_dismiss_and_history_clear_do_not_restore_old_reply(self):
        app = self.app
        for action in (app._dismiss_chat_reply, lambda: app._show_chat_phase("cleared")):
            app._show_chat_phase("reply", "이전 답변")
            action()
            app._show_chat_phase("idle")
            self.assertEqual((app._chat_phase, app._last_chat_reply), ("idle", ""))

    def test_full_reply_and_timer_character_changes_preserve_answer(self):
        app = self.app
        app._assistant_windows = Mock()
        text = "첫째\n둘째\n셋째\n넷째\n다섯째"
        app._show_chat_phase("reply", text)
        app._activate_chat_reply()
        app._assistant_windows.open_reply.assert_called_once_with(text)
        self.assertEqual(app._chat_phase, "reply")
        app._set_character("away")
        self.assertEqual(app.character_role, "away")
        self.assertEqual(app._last_chat_reply, text)

    def test_visible_or_drafted_chat_and_recent_chat_block_all_proactive_calls(self):
        app = self.app
        app._assistant_windows = Mock()
        app._assistant_windows.is_chat_active.return_value = True
        for event in ("periodic", "return", "rest"):
            app._request_proactive(event, Mock() if event == "rest" else None)
        app._assistant_service.proactive.assert_not_called()
        app._assistant_windows.is_chat_active.return_value = False
        with patch("assistant_ai.desktop.time.monotonic", return_value=1000):
            app._assistant_last_chat_at = 750
            app._request_proactive("return")
        app._assistant_service.proactive.assert_not_called()

    def test_hidden_reply_can_yield_to_valid_ai_after_quiet_period(self):
        app = self.app
        with patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app._show_chat_phase("reply", "이전 답변")
        app._assistant_service.proactive.return_value = "오후 흐름은 어때요?"
        with patch("assistant_ai.desktop.time.monotonic", return_value=500):
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=3)()
        app.speech.configure.assert_called_once_with(text="오후 흐름은 어때요?")
        self.assertEqual(app._chat_phase, "idle")

    def test_periodic_honors_configured_interval_and_active_work_only(self):
        app = self.app
        context = app._assistant_tools.context()
        app._assistant_tools.context = lambda: context
        app._assistant_last_periodic = 100
        with patch("assistant_ai.desktop.time.monotonic", return_value=1299):
            app._request_proactive("periodic")
        app._assistant_service.proactive.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=1300):
            context["is_away"] = True
            app._request_proactive("periodic")
            context.update(is_away=False, workday_mode="leave")
            app._request_proactive("periodic")
            app._assistant_service.proactive.assert_not_called()
            context["workday_mode"] = "normal"
            app._assistant_service.proactive.return_value = None
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=3)()
        self.assertEqual(app._assistant_service.proactive.call_count, 1)

    def test_opening_chat_before_proactive_finishes_preserves_current_display(self):
        app = self.app
        app._assistant_service.proactive.return_value = "늦게 도착한 말"
        app._request_proactive("return")
        callback = app.ui_commands.get(timeout=3)
        app._assistant_windows = Mock()
        app._assistant_windows.is_chat_active.return_value = True
        callback()
        app.speech.configure.assert_not_called()

    def test_normal_dialogue_rotates_time_context_and_personality_without_changing_alerts(self):
        app = self.app
        app.preferences.personality = "warm"
        with patch("assistant_ai.desktop.maybe_pick_custom", return_value=None), \
             patch("assistant_ai.desktop.maybe_pick_rare", return_value=None), \
             patch("assistant_ai.desktop.maybe_pick_daily_temperament", return_value=None), \
             patch("assistant_ai.desktop.datetime") as clock, \
             patch("assistant_ai.desktop.pick", side_effect=lambda kind, personality: f"{kind}:{personality}"):
            clock.now.return_value.hour = 9
            self.assertEqual([app._local_dialogue("playful", "normal") for _ in range(4)],
                             ["morning:warm", "playful:warm", "playful:warm", "morning:warm"])
            self.assertEqual(app._local_dialogue("leave", "leave"), "leave:warm")
            app._say("return", "복귀 시간 5분 기록")
            app.speech.configure.assert_called_with(text="복귀 시간 5분 기록")


if __name__ == "__main__":
    unittest.main()
