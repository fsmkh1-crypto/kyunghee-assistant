from dataclasses import replace
import unittest

from assistant_ai.timer_tools import TOOLS, TimerTools, validate_arguments
from settings import UserSettings
from state import fresh_state
from timer_engine import TimerEngine
from workday import WorkdayState


class TimerApp:
    def __init__(self):
        self.state = fresh_state()
        self.preferences = UserSettings()
        self.mode = "normal"
        self.engine = TimerEngine(self.state, idle_provider=lambda: (0.0, 0))
        self.actions = []
        self.controls = {}

    def _current_workday_state(self):
        return WorkdayState(self.mode, None)

    def accept_break(self):
        self.actions.append("start_break")
        self.engine.accept_break()

    def toggle_manual_away(self):
        self.actions.append("resume" if self.state.session.is_away else "start_away")
        if self.state.session.is_away:
            self.engine.stop_manual_away()
        else:
            self.engine.start_manual_away()

    def snooze_break(self):
        self.actions.append("snooze_break")
        self.engine.snooze_break()

    def apply_preferences(self, preferences):
        self.preferences = preferences
        self.engine.set_break_interval(preferences.break_interval_minutes * 60)
        self.engine.set_snooze_interval(preferences.snooze_minutes * 60)

    def _sync_assistant_preference_controls(self, changes):
        self.controls.update(changes)


class AssistantTimerToolsTests(unittest.TestCase):
    def setUp(self):
        self.app = TimerApp()
        self.tools = TimerTools(self.app)
        self.confirmations = []

    def confirm(self, description):
        self.confirmations.append(description)
        return True

    def test_strict_schemas_and_invalid_calls_are_rejected(self):
        for tool in TOOLS:
            self.assertTrue(tool["strict"])
            self.assertFalse(tool["parameters"]["additionalProperties"])
            self.assertEqual(set(tool["parameters"]["required"]), set(tool["parameters"]["properties"]))
        invalid = (
            ("quit", {}),
            ("get_timer_status", {"extra": True}),
            ("get_usage_stats", {"days": True}),
            ("set_notification_enabled", {"kind": "break", "enabled": 1}),
            ("set_notification_minutes", {"kind": "snooze", "minutes": 31}),
            ("set_workday_schedule", {"wind_down": "1:30", "leave_mode": None, "strong_leave": None, "late_leave": None}),
        )
        for name, args in invalid:
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_arguments(name, args)
        self.assertEqual(self.app.actions, [])
        self.assertEqual(self.confirmations, [])

    def test_stats_and_status_use_live_engine_and_do_not_confirm(self):
        self.app.state.daily.active_seconds = 900
        self.app.state.daily.away_seconds = 100
        status = self.tools.execute("get_timer_status", {}, self.confirm)
        stats = self.tools.execute("get_usage_stats", {"days": 1}, self.confirm)
        self.assertEqual(status["today_active_seconds"], 900)
        self.assertEqual(status["next_break_in_seconds"], 3600)
        self.assertEqual(stats["active_ratio_percent"], 90)
        self.assertEqual(self.confirmations, [])

    def test_context_includes_local_clock_personality_events_and_recent_speech(self):
        self.app.preferences = replace(self.app.preferences, personality="strict", custom_dialogue="짧게 말하기")
        self.app._assistant_events = [{"date": self.app.state.daily.day, "event": "return"}, {"date": "1999-01-01", "event": "away"}]
        self.app._assistant_recent_dialogue = ["물 마시기"]
        context = self.tools.context()
        self.assertIn("T", context["current_time"])
        self.assertTrue(context["timezone"])
        self.assertEqual(context["personality"], "strict")
        self.assertEqual(context["custom_dialogue"], "짧게 말하기")
        self.assertEqual(context["recent_dialogue"], ["물 마시기"])
        self.assertEqual([item["event"] for item in context["today_events"]], ["return"])

    def test_actions_wait_for_confirmation_and_report_real_result(self):
        result = self.tools.execute("set_timer_action", {"action": "start_break"}, lambda _: False)
        self.assertFalse(result["ok"])
        self.assertFalse(self.app.state.session.is_away)
        result = self.tools.execute("set_timer_action", {"action": "start_break"}, self.confirm)
        self.assertTrue(result["changed"])
        self.assertTrue(result["is_away"])
        self.assertIsNone(result["next_break_in_seconds"])
        self.assertEqual(self.app.actions, ["start_break"])

    def test_revalidates_state_after_confirmation(self):
        self.app.engine.start_manual_away()

        def confirm_after_auto_resume(_):
            self.app.engine.stop_manual_away()
            return True

        result = self.tools.execute("set_timer_action", {"action": "resume"}, confirm_after_auto_resume)
        self.assertFalse(result["ok"])
        self.assertFalse(self.app.state.session.is_away)
        self.assertEqual(self.app.actions, [])

    def test_snooze_only_changes_a_due_break_in_work_modes(self):
        self.app.state.session.continuous_seconds = 3600
        self.app.mode = "leave"
        result = self.tools.execute("set_timer_action", {"action": "snooze_break"}, self.confirm)
        self.assertFalse(result["ok"])
        self.assertEqual(self.confirmations, [])
        self.app.mode = "normal"
        result = self.tools.execute("set_timer_action", {"action": "snooze_break"}, self.confirm)
        self.assertTrue(result["changed"])
        self.assertEqual(result["next_break_in_seconds"], 300)
        self.assertIn("5분", self.confirmations[0])

    def test_preferences_save_only_the_selected_fields(self):
        self.app.preferences = replace(self.app.preferences, show_message=False)
        result = self.tools.execute("set_notification_minutes", {"kind": "break_interval", "minutes": 45}, self.confirm)
        self.assertTrue(result["changed"])
        self.assertEqual(self.app.engine.remaining_to_break(), 2700)
        self.assertEqual(self.app.controls, {"break_interval_minutes": 45})
        self.assertFalse(self.app.preferences.show_message)
        self.assertIn("45분", self.confirmations[0])

    def test_out_of_order_workday_settings_cannot_be_confirmed(self):
        result = self.tools.execute(
            "set_workday_schedule",
            {"wind_down": "20:00", "leave_mode": None, "strong_leave": None, "late_leave": None},
            self.confirm,
        )
        self.assertFalse(result["ok"])
        self.assertEqual(self.confirmations, [])
        self.assertEqual(self.app.preferences.wind_down, "17:00")
