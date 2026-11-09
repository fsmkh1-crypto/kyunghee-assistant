"""Exercise the real mixin without opening Tk windows or contacting an API."""
from collections import deque
from dataclasses import replace
import importlib.util
import os
from pathlib import Path
import queue
import tempfile
import threading
import time
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
                if self._use_real_dialogue:
                    from app import App
                    return App._update_dialogue(self)
                self.last_dialogue_at = time.monotonic()
            def _tick_safe(self):
                self._update_dialogue()
            def _cycle_message(self, event=None):
                self.local_calls.append("manual")
            def _set_character(self, role):
                self.character_role = role
            def _visible_speech(self):
                return self.speech
            def _say(self, kind, text=None, work_mode="normal"):
                self.speech.configure(text=text)
                self.last_dialogue_at = time.monotonic()
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
        app._use_real_dialogue = False
        app._assistant_pending = None
        app._assistant_shutdown = threading.Event()
        app._assistant_events = deque(maxlen=40)
        app._assistant_recent_dialogue = deque(maxlen=12)
        app._assistant_last_attempt = app._assistant_last_periodic = float("-inf")
        app._assistant_last_chat_at = float("-inf")
        app._assistant_important_event_at = float("-inf")
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
        app.state = SimpleNamespace(session=SimpleNamespace(is_away=False, ignored_breaks=0))
        app.engine = SimpleNamespace(remaining_to_break=lambda: 3600)
        app._current_workday_state = lambda: SimpleNamespace(mode=app.last_work_mode)
        app.break_gate = SimpleNamespace(last_shown_at=0)
        app.toast = None
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
        app._assistant_service.load_settings.return_value = SimpleNamespace(proactive_interval_minutes=20, chatter_enabled=False)
        app._assistant_service.proactive_diagnostics.return_value = {"state": "idle", "retry_after_seconds": 0}

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

    def test_inline_reply_focus_and_timer_character_changes_preserve_answer(self):
        app = self.app
        app._assistant_windows = Mock()
        text = "첫째\n둘째\n셋째\n넷째\n다섯째"
        app._show_chat_phase("reply", text)
        app._activate_chat_reply()
        app._chat_speech.configure.assert_called_with(text=text)
        app._chat_speech.focus_reading.assert_called_once_with()
        app._assistant_windows.open_reply.assert_not_called()
        app._open_assistant_chat.assert_not_called()
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

    def test_one_minute_timer_is_independent_of_real_local_rotation_and_response_time(self):
        app = self.app
        app._use_real_dialogue = True
        app._assistant_service.load_settings.return_value.proactive_interval_minutes = 1
        app._assistant_last_periodic = app._assistant_last_attempt = 0
        app.last_dialogue_at = 58
        app._assistant_service.proactive.side_effect = ["첫 AI 대화", "다음 AI 대화"]
        with patch("assistant_ai.desktop.time.monotonic", return_value=59):
            app._tick_safe()
        app._assistant_service.proactive.assert_not_called()
        app.speech.configure.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._tick_safe()
            first = app.ui_commands.get(timeout=3)
        with patch("assistant_ai.desktop.time.monotonic", return_value=65):
            first()
        self.assertEqual(app.last_dialogue_at, 65)
        with patch("assistant_ai.desktop.time.monotonic", return_value=119):
            app._tick_safe()
        self.assertEqual(app._assistant_service.proactive.call_count, 1)
        with patch("assistant_ai.desktop.time.monotonic", return_value=120):
            app._tick_safe()
            second = app.ui_commands.get(timeout=3)
        with patch("assistant_ai.desktop.time.monotonic", return_value=125):
            # Ordinary rotation is due now, while the second request is still
            # waiting in the UI queue. It must not invalidate the new AI text.
            app._tick_safe()
            second()
        self.assertEqual(app._assistant_service.proactive.call_count, 2)
        app.speech.configure.assert_called_with(text="다음 AI 대화")
        self.assertEqual(app._assistant_last_chat_at, float("-inf"))

    def test_ai_chatter_never_substitutes_local_lines_on_failure_or_offline(self):
        app = self.app
        settings = app._assistant_service.load_settings.return_value
        settings.chatter_enabled = True
        settings.proactive_interval_minutes = 1
        app._assistant_last_periodic = 0
        app._assistant_service.can_proactively_speak.return_value = False
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._tick_safe()
        self.assertEqual(app.local_calls, [])
        app.speech.configure.assert_not_called()
        app._assistant_service.proactive.assert_not_called()
        app._assistant_service.can_proactively_speak.return_value = True
        app._assistant_service.proactive.side_effect = OSError("fake offline")
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._tick_safe()
            app.ui_commands.get(timeout=3)()
        with patch("assistant_ai.desktop.time.monotonic", return_value=119):
            app._tick_safe()
        self.assertEqual(app._assistant_service.proactive.call_count, 1)
        app.speech.configure.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=120):
            app._tick_safe()
            app.ui_commands.get(timeout=3)()
        self.assertEqual(app._assistant_service.proactive.call_count, 2)
        self.assertEqual(app.local_calls, [])

    def test_chatter_off_restores_local_rotation_without_changing_existing_ai_choice(self):
        app = self.app
        settings = app._assistant_service.load_settings.return_value
        settings.chatter_enabled = True
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._update_dialogue()
        self.assertEqual(app.local_calls, [])
        app._assistant_pending = SimpleNamespace(cancel=threading.Event(), started_at=60)
        app._assistant_pending.cancel.set()
        settings.chatter_enabled = False
        with patch("assistant_ai.desktop.time.monotonic", return_value=61):
            app._update_dialogue()
        self.assertEqual(app.local_calls, ["periodic"])
        self.assertIsNone(app._assistant_pending)
        app._assistant_service.can_proactively_speak.assert_not_called()

    def test_reading_protection_keeps_answer_but_real_timer_transition_still_runs(self):
        app = self.app
        app._assistant_service.load_settings.return_value.chatter_enabled = True
        app._last_chat_reply = "읽는 중인 답변"
        with patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app._note_assistant_activity()
        with patch("assistant_ai.desktop.time.monotonic", return_value=399):
            app._update_dialogue()
        self.assertEqual(app.local_calls, [])
        self.assertEqual(app._last_chat_reply, "읽는 중인 답변")
        app._current_workday_state = lambda: SimpleNamespace(mode="leave")
        with patch("assistant_ai.desktop.time.monotonic", return_value=399):
            app._update_dialogue()
        self.assertEqual(app.local_calls, ["periodic"])
        app._assistant_last_chat_at = float("-inf")
        app.last_work_mode = "leave"
        with patch("assistant_ai.desktop.time.monotonic", return_value=500):
            app._update_dialogue()
        self.assertEqual(app.local_calls, ["periodic", "periodic"])

    def test_diagnostics_distinguish_off_quiet_activity_and_next_attempt_without_api_call(self):
        from assistant_ai.config import AISettings
        app = self.app
        app._assistant_last_periodic = 0
        settings = AISettings(enabled=True, chatter_enabled=True)
        app._assistant_service.load_settings.return_value = settings
        app._assistant_service.has_key.return_value = True
        app._assistant_service.proactive_diagnostics.return_value = {
            "state": "idle", "retry_after_seconds": 0, "last_message": "이번에는 새로 덧붙일 말이 없어 쉬었어요.",
            "last_outcome": "silent", "last_updated_at": "2026-11-09T10:00:00+09:00",
        }
        with patch("assistant_ai.desktop.time.monotonic", return_value=59):
            status = app._proactive_status()
        self.assertEqual(status["next_in_seconds"], 1)
        self.assertIn("1초", status["reason"])
        self.assertEqual(status["last_outcome"], "silent")
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            self.assertIn("시도할 수", app._proactive_status()["reason"])
            app._assistant_service.load_settings.return_value = replace(settings, chatter_enabled=False)
            self.assertIn("모두 꺼져", app._proactive_status()["reason"])
            app._assistant_service.load_settings.return_value = replace(settings, proactive_quiet_until=__import__("datetime").date.today().isoformat())
            self.assertIn("오늘은", app._proactive_status()["reason"])
        app._assistant_service.proactive.assert_not_called()

    def test_chatter_only_still_protects_important_timer_alert_for_sixty_seconds(self):
        app = self.app
        settings = app._assistant_service.load_settings.return_value
        settings.chatter_enabled = True
        settings.proactive_interval_minutes = 1
        app._assistant_service.can_proactively_speak.side_effect = lambda event=None: event in (None, "periodic")
        app._assistant_service.proactive.return_value = "새 AI 대화"
        with patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app._request_proactive("rest", Mock())
            self.assertIn("중요한", self._important_status_reason(app))
        with patch("assistant_ai.desktop.time.monotonic", return_value=159):
            app._request_proactive("periodic")
        app._assistant_service.proactive.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=160):
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=3)()
        self.assertEqual(app._assistant_service.proactive.call_count, 1)
        app.speech.configure.assert_called_with(text="새 AI 대화")

    def _important_status_reason(self, app):
        from assistant_ai.config import AISettings
        original = app._assistant_service.load_settings.return_value
        app._assistant_service.load_settings.return_value = AISettings(enabled=True, chatter_enabled=True)
        app._assistant_service.proactive_diagnostics.return_value = {"state": "idle", "retry_after_seconds": 0}
        try:
            return app._proactive_status()["reason"]
        finally:
            app._assistant_service.load_settings.return_value = original

    def test_new_important_timer_message_invalidates_waiting_periodic_text(self):
        app = self.app
        app._assistant_service.proactive.return_value = "이전 상황에서 만든 말"
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._request_proactive("periodic")
            callback = app.ui_commands.get(timeout=3)
        with patch("assistant_ai.desktop.time.monotonic", return_value=61):
            app._say("return", "복귀했어요. 실제 기록을 확인했어요.")
            callback()
        app.speech.configure.assert_called_once_with(text="복귀했어요. 실제 기록을 확인했어요.")

    def test_worker_clock_offsets_do_not_skip_an_extra_interval_in_either_mode(self):
        from assistant_ai.service import AssistantService
        for event in ("periodic", "return"):
            for delay in (0.01, 0.5):
                with self.subTest(event=event, worker_delay=delay), tempfile.TemporaryDirectory() as directory:
                    self.setUp()
                    app = self.app
                    clock = [0.0]
                    workers = []
                    with patch("assistant_ai.desktop.time.monotonic", side_effect=lambda: clock[0]), \
                         patch("assistant_ai.service.ResponsesClient") as client, \
                         patch("assistant_ai.desktop.threading.Thread",
                               side_effect=lambda **kwargs: SimpleNamespace(start=lambda: workers.append(kwargs["target"]))):
                        service = AssistantService(Path(directory))
                        settings = replace(service.load_settings(), enabled=True, proactive_enabled=True,
                                           chatter_enabled=event == "periodic",
                                           proactive_interval_minutes=1 if event == "periodic" else 20)
                        service.save_settings(settings, new_key="fake-clock-test-key")
                        app._assistant_service = service
                        app._assistant_last_attempt = float("-inf")
                        app._assistant_last_periodic = 0.0
                        client.return_value.respond.return_value = SimpleNamespace(text="SILENT", status="completed")

                        # For timer events, a twenty-minute periodic setting
                        # must not block the first event or its sixty-second gap.
                        first_at = 60.0 if event == "periodic" else 10.0
                        clock[0] = first_at
                        app._request_proactive(event)
                        self.assertEqual(len(workers), 1)
                        clock[0] = first_at + delay
                        workers.pop(0)()
                        app.ui_commands.get(timeout=2)()
                        self.assertEqual(client.return_value.respond.call_count, 1)
                        previous_clocks = (app._assistant_last_attempt, app._assistant_last_periodic)

                        clock[0] = first_at + 60
                        app._request_proactive(event)
                        self.assertEqual(workers, [])
                        self.assertEqual((app._assistant_last_attempt, app._assistant_last_periodic), previous_clocks)
                        self.assertEqual(client.return_value.respond.call_count, 1)

                        clock[0] = first_at + 61
                        app._request_proactive(event)
                        self.assertEqual(len(workers), 1)
                        clock[0] += delay
                        workers.pop(0)()
                        app.ui_commands.get(timeout=2)()
                        self.assertEqual(client.return_value.respond.call_count, 2)

    def test_waiting_for_cancelled_transport_does_not_advance_ui_schedule(self):
        app = self.app
        app._assistant_service.load_settings.return_value.proactive_interval_minutes = 1
        app._assistant_last_attempt = app._assistant_last_periodic = 0
        app._assistant_service.proactive_diagnostics.return_value = {"state": "requesting", "retry_after_seconds": 0}
        with patch("assistant_ai.desktop.time.monotonic", return_value=60):
            app._request_proactive("periodic")
        app._assistant_service.proactive.assert_not_called()
        self.assertEqual((app._assistant_last_attempt, app._assistant_last_periodic), (0, 0))
        app._assistant_service.proactive_diagnostics.return_value = {"state": "idle", "retry_after_seconds": 0}
        app._assistant_service.proactive.return_value = None
        with patch("assistant_ai.desktop.time.monotonic", return_value=61):
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=2)()
        self.assertEqual(app._assistant_service.proactive.call_count, 1)


if __name__ == "__main__":
    unittest.main()
