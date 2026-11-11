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
                if self._use_real_tick:
                    from app import App
                    return App._tick_safe(self)
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
            def toggle_manual_away(self):
                from app import App
                return App.toggle_manual_away(self)
            def accept_break(self):
                from app import App
                return App.accept_break(self)
            def snooze_break(self):
                from app import App
                return App.snooze_break(self)
            def _destroy_toast(self):
                self.toast = None
            def show_toast(self, text):
                self.toast = SimpleNamespace(winfo_exists=lambda: True, body_label=Mock())
                self.toast.body_label.configure(text=text)
                self.shown_toasts.append(("message", text))
            def show_break_toast(self, text, allow_snooze=True):
                if not self._suppress_toast:
                    self.show_toast(text)
                    self.shown_toasts[-1] = ("break", text, allow_snooze)
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
        app._use_real_tick = False
        app._suppress_toast = False
        app.shown_toasts = []
        app._assistant_pending = None
        app._assistant_shutdown = threading.Event()
        app._assistant_events = deque(maxlen=40)
        app._assistant_recent_dialogue = deque(maxlen=12)
        app._assistant_last_attempt = app._assistant_last_periodic = float("-inf")
        app._assistant_last_chat_at = float("-inf")
        app._assistant_important_event_at = float("-inf")
        app._assistant_dialogue_mode = None
        app._assistant_notification_event = None
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
        app._speech_text = ""
        def configure_speech(*, text):
            app._speech_text = text
        app.speech.configure.side_effect = configure_speech
        app.speech.cget.side_effect = lambda field: app._speech_text
        app._apply_widget_appearance = Mock()
        app._update_ui = Mock()
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
        app._assistant_service.record_notification.assert_not_called()
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
        app._assistant_service.record_notification.assert_not_called()

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

    def test_ten_minutes_of_real_worry_and_nag_rotation_do_not_starve_proactive(self):
        for ignored in (0, 1, 2):
            for chatter in (False, True):
                with self.subTest(ignored_breaks=ignored, chatter=chatter):
                    self.setUp()
                    app = self.app
                    app._use_real_dialogue = True
                    app.state.session.ignored_breaks = ignored
                    settings = app._assistant_service.load_settings.return_value
                    settings.proactive_enabled = True
                    settings.chatter_enabled = chatter
                    settings.proactive_interval_minutes = 1
                    app._assistant_last_periodic = app._assistant_last_attempt = 0
                    app._assistant_important_event_at = 0
                    # Silent results leave the real local rotation clock alone:
                    # worry/nag will run at every 60-second boundary.
                    app._assistant_service.proactive.return_value = None
                    clock = [0]
                    with patch("assistant_ai.desktop.time.monotonic", side_effect=lambda: clock[0]), \
                         patch.object(app, "_local_dialogue", side_effect=lambda kind, mode: kind), \
                         patch("assistant_ai.desktop.threading.Thread",
                               side_effect=lambda **kwargs: SimpleNamespace(start=kwargs["target"])):
                        for second in range(1, 601):
                            clock[0] = second
                            app._tick_safe()
                            while not app.ui_commands.empty():
                                app.ui_commands.get_nowait()()
                    self.assertEqual(app._assistant_service.proactive.call_count, 10)
                    self.assertEqual(app._assistant_important_event_at, 0)
                    self.assertEqual(app.speech.configure.call_count, 0 if chatter else 10)
                    if not chatter:
                        self.assertEqual(app._speech_text, ("playful", "worry", "nag")[ignored])
                    app._assistant_service.record_notification.assert_not_called()
                    app._assistant_service.save_settings.assert_not_called()
                    self.assertTrue(settings.proactive_enabled)
                    self.assertEqual(settings.chatter_enabled, chatter)

    def test_workday_transition_between_mode_reads_still_records_real_alert(self):
        app = self.app
        app._use_real_dialogue = True
        app._current_workday_state = Mock(side_effect=[SimpleNamespace(mode="normal"), SimpleNamespace(mode="leave")])
        with patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app._update_dialogue()
        self.assertEqual(app.last_work_mode, "leave")
        self.assertEqual(app._assistant_important_event_at, 100)
        app._assistant_service.record_notification.assert_called_once_with(
            app._speech_text, event="leave", origin="local_event")
        self.assertIsNone(app._assistant_dialogue_mode)

    def test_real_break_due_alert_keeps_sixty_second_guard_and_records_once(self):
        app = self.app
        app._use_real_tick = app._use_real_dialogue = True
        app.preferences.break_reminders = True
        app.state.daily = SimpleNamespace(break_reminders_suppressed=False)
        app.engine.tick = lambda: SimpleNamespace(became_active=False, break_due=True)
        def show_gate(due, now):
            app.break_gate.last_shown_at = now
            return due
        app.break_gate.should_show = show_gate
        app._assistant_service.can_proactively_speak.side_effect = lambda event=None: event == "periodic"
        app._assistant_service.load_settings.return_value.proactive_interval_minutes = 1
        app._assistant_service.proactive.return_value = "다음 대화"
        app._assistant_windows = Mock()
        app._assistant_windows.is_chat_active.return_value = False
        with patch("assistant_ai.desktop.time.monotonic", return_value=100), \
             patch("app.rollover_daily"), patch("app.pick", return_value="이제 쉬어 갈 시간이에요."):
            app._tick_safe()
        self.assertEqual(app.shown_toasts, [("break", "이제 쉬어 갈 시간이에요.", True)])
        app._assistant_service.record_notification.assert_called_once_with(
            "이제 쉬어 갈 시간이에요.", event="rest", origin="local_event")
        app._assistant_windows.refresh_chat_history.assert_called_once_with()
        self.assertEqual(app._assistant_important_event_at, 100)
        with patch("assistant_ai.desktop.time.monotonic", return_value=159):
            app._request_proactive("periodic")
        app._assistant_service.proactive.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=160):
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=3)()
        app._assistant_service.proactive.assert_called_once()

    def test_actual_local_notifications_join_conversation_once_with_ai_disabled(self):
        from assistant_ai.service import AssistantService
        with tempfile.TemporaryDirectory() as directory, \
             patch("assistant_ai.service.ResponsesClient") as client, \
             patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app = self.app
            app._assistant_service = AssistantService(Path(directory))
            self.assertFalse(app._assistant_service.load_settings().enabled)
            app._assistant_windows = Mock()
            app._assistant_windows.is_chat_active.return_value = False
            app.break_gate.reset = Mock()
            def away(value):
                app.state.session.is_away = value
            def snooze():
                app.state.session.ignored_breaks += 1
            app.engine.start_manual_away = lambda: away(True)
            app.engine.stop_manual_away = lambda: away(False)
            app.engine.accept_break = lambda: away(True)
            app.engine.snooze_break = snooze
            app._show_chat_phase("reply", "기존에 받은 답변")
            app._assistant_last_chat_at = 5

            app.show_break_toast("지금은 휴식할 시간이에요.")
            app.snooze_break()
            app.accept_break()
            app.toggle_manual_away()
            app.toggle_manual_away()
            app._use_real_dialogue = True
            app._current_workday_state = lambda: SimpleNamespace(mode="leave")
            app._update_dialogue()
            # Same-mode workday dialogue is routine, even though its kind
            # matches the real transition above.
            app.state.session.is_away = False
            with patch("assistant_ai.desktop.time.monotonic", return_value=160):
                app._update_dialogue()

            turns = app._assistant_service.recent_turns()
            self.assertEqual([turn.event for turn in turns], ["rest", "snooze", "break_started", "return", "away", "leave"])
            self.assertTrue(all(turn.origin == "local_event" and turn.user == "" and turn.assistant for turn in turns))
            self.assertTrue(all(turn.id < 0 for turn in turns))
            self.assertEqual(app._assistant_service.recent_turns(scope="saved"), [])
            self.assertEqual(app._assistant_windows.refresh_chat_history.call_count, 6)
            self.assertEqual(app._assistant_last_chat_at, 5)
            self.assertEqual(app._assistant_important_event_at, 100)
            self.assertEqual(app._chat_phase, "idle")
            app._assistant_windows.open_chat.assert_not_called()
            app.root.focus_force.assert_not_called()
            client.assert_not_called()

    def test_suppressed_break_toast_does_not_create_phantom_history(self):
        app = self.app
        app._suppress_toast = True
        app.toast = SimpleNamespace(winfo_exists=lambda: True)
        app._show_chat_phase("reply", "읽던 답변")
        app.show_break_toast("보이지 않은 휴식 알림")
        app._assistant_service.record_notification.assert_not_called()
        self.assertEqual(app._chat_phase, "reply")
        self.assertEqual(app._assistant_important_event_at, float("-inf"))
        app.speech.configure.assert_not_called()

    def test_notification_storage_and_history_refresh_failures_leave_timer_working(self):
        for failing in ("storage", "refresh"):
            with self.subTest(failure=failing):
                self.setUp()
                app = self.app
                app._assistant_windows = Mock()
                if failing == "storage":
                    app._assistant_service.record_notification.side_effect = OSError("fake disk failure")
                else:
                    app._assistant_windows.refresh_chat_history.side_effect = RuntimeError("fake closed window")
                with patch("assistant_ai.desktop.core.log.warning") as warning:
                    app.show_break_toast("휴식 안내는 계속 보여요.")
                self.assertEqual(app._speech_text, "휴식 안내는 계속 보여요.")
                self.assertEqual(len(app.shown_toasts), 1)
                warning.assert_called_once()

    def test_local_notification_does_not_extend_actual_reading_five_minute_guard(self):
        app = self.app
        app._assistant_service.load_settings.return_value.proactive_interval_minutes = 1
        app._assistant_service.proactive.return_value = "읽기 뒤 새 대화"
        with patch("assistant_ai.desktop.time.monotonic", return_value=0):
            app._show_chat_phase("reply", "읽는 중인 답변")
            app._note_assistant_activity()
        with patch("assistant_ai.desktop.time.monotonic", return_value=100):
            app._say("return", "복귀했어요.")
        self.assertEqual(app._assistant_last_chat_at, 0)
        with patch("assistant_ai.desktop.time.monotonic", return_value=299):
            app._request_proactive("periodic")
        app._assistant_service.proactive.assert_not_called()
        with patch("assistant_ai.desktop.time.monotonic", return_value=300):
            app._request_proactive("periodic")
            app.ui_commands.get(timeout=3)()
        app._assistant_service.proactive.assert_called_once()

    def test_proactive_history_records_full_text_only_once_after_delivery(self):
        text = "첫 안내\n" + "끝까지 기록할 긴 안내예요. " * 20 + "ㅋ"
        for with_toast in (False, True):
            with self.subTest(toast=with_toast):
                self.setUp()
                app = self.app
                app._assistant_service.proactive.return_value = text
                app._assistant_windows = Mock()
                app._assistant_windows.is_chat_active.return_value = False
                toast = Mock() if with_toast else None
                app.toast = toast
                with patch("assistant_ai.desktop.time.monotonic", return_value=100):
                    app._request_proactive("rest" if with_toast else "return", toast)
                    finish = app.ui_commands.get(timeout=3)
                    app._assistant_service.record_notification.assert_not_called()
                    finish()
                    finish()
                app._assistant_service.record_notification.assert_called_once_with(
                    text, event="rest" if with_toast else "return", origin="proactive")
                app._assistant_windows.refresh_chat_history.assert_called_once_with()
                if with_toast:
                    toast.body_label.configure.assert_called_once_with(text=text[:89].rstrip() + "…")
                else:
                    app.speech.configure.assert_called_once_with(text=text)
                self.assertEqual(app._assistant_last_chat_at, float("-inf"))

    def test_stale_or_undelivered_proactive_text_never_enters_history(self):
        for reason in ("age", "revision", "context", "hidden", "replaced_toast", "destroyed_toast", "empty"):
            with self.subTest(reason=reason):
                self.setUp()
                app = self.app
                app._assistant_service.proactive.return_value = "전달되지 않은 응답" if reason != "empty" else None
                toast = Mock() if reason in {"replaced_toast", "destroyed_toast"} else None
                app.toast = toast
                with patch("assistant_ai.desktop.time.monotonic", return_value=100):
                    app._request_proactive("rest" if toast else "return", toast)
                    finish = app.ui_commands.get(timeout=3)
                if reason == "revision":
                    app._assistant_service.revision += 1
                elif reason == "context":
                    context = {**app._assistant_tools.context(), "is_away": True}
                    app._assistant_tools.context = lambda: context
                elif reason == "hidden":
                    app.root.winfo_viewable.return_value = False
                elif reason == "replaced_toast":
                    app.toast = Mock()
                elif reason == "destroyed_toast":
                    toast.winfo_exists.return_value = False
                with patch("assistant_ai.desktop.time.monotonic", return_value=126 if reason == "age" else 101):
                    finish()
                app._assistant_service.record_notification.assert_not_called()

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
