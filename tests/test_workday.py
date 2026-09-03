import unittest
from datetime import datetime

from settings import WorkdayPolicy
from workday import apply_reminder_preference, classify_workday, should_encourage_more_work


class WorkdayTests(unittest.TestCase):
    def test_normal_before_1700(self):
        s = classify_workday(datetime(2026, 9, 2, 16, 59), 3 * 3600)
        self.assertEqual(s.mode, "normal")
        self.assertTrue(should_encourage_more_work(s.mode))

    def test_wind_down_at_1700(self):
        s = classify_workday(datetime(2026, 9, 2, 17, 0), 3 * 3600)
        self.assertEqual(s.mode, "wind_down")
        self.assertTrue(should_encourage_more_work(s.mode))

    def test_leave_mode_at_1730(self):
        s = classify_workday(datetime(2026, 9, 2, 17, 30), 3 * 3600)
        self.assertEqual(s.mode, "leave")
        self.assertFalse(should_encourage_more_work(s.mode))

    def test_strong_leave_at_1800(self):
        s = classify_workday(datetime(2026, 9, 2, 18, 0), 3 * 3600)
        self.assertEqual(s.mode, "strong_leave")

    def test_late_leave_at_1830(self):
        s = classify_workday(datetime(2026, 9, 2, 18, 30), 3 * 3600)
        self.assertEqual(s.mode, "late_leave")

    def test_nine_hour_limit_overrides_clock(self):
        s = classify_workday(datetime(2026, 9, 2, 15, 0), 9 * 3600)
        self.assertEqual(s.mode, "hard_stop")
        self.assertFalse(should_encourage_more_work(s.mode))

    def test_custom_policy_is_applied(self):
        policy = WorkdayPolicy(
            wind_down=datetime.strptime("16:00", "%H:%M").time(),
            leave_mode=datetime.strptime("16:30", "%H:%M").time(),
            strong_leave=datetime.strptime("17:00", "%H:%M").time(),
            late_leave=datetime.strptime("17:30", "%H:%M").time(),
        )
        state = classify_workday(datetime(2026, 9, 2, 16, 30), 3 * 3600, policy)
        self.assertEqual(state.mode, "leave")

    def test_disabled_reminders_hide_clock_based_mode(self):
        state = classify_workday(datetime(2026, 9, 2, 18, 30), 3 * 3600)
        filtered = apply_reminder_preference(state, enabled=False)
        self.assertEqual(filtered.mode, "normal")

    def test_disabled_reminders_preserve_hard_stop(self):
        state = classify_workday(datetime(2026, 9, 2, 15, 0), 9 * 3600)
        filtered = apply_reminder_preference(state, enabled=False)
        self.assertEqual(filtered.mode, "hard_stop")
        self.assertFalse(should_encourage_more_work(filtered.mode))


if __name__ == "__main__":
    unittest.main()
