import unittest

from break_reminder import BreakReminderGate


class BreakReminderGateTests(unittest.TestCase):
    def test_first_due_shows_immediately(self):
        gate = BreakReminderGate(repeat_interval_sec=300)
        self.assertTrue(gate.should_show(True, 100.0))
        self.assertFalse(gate.should_show(True, 101.0))

    def test_due_repeats_after_five_minutes(self):
        gate = BreakReminderGate(repeat_interval_sec=300)
        self.assertTrue(gate.should_show(True, 100.0))
        self.assertFalse(gate.should_show(True, 399.9))
        self.assertTrue(gate.should_show(True, 400.0))
        self.assertFalse(gate.should_show(True, 401.0))
        self.assertTrue(gate.should_show(True, 700.0))

    def test_reset_rearms_immediately(self):
        gate = BreakReminderGate(repeat_interval_sec=300)
        self.assertTrue(gate.should_show(True, 100.0))
        gate.reset()
        self.assertTrue(gate.should_show(True, 101.0))

    def test_not_due_never_arms(self):
        gate = BreakReminderGate(repeat_interval_sec=300)
        self.assertFalse(gate.should_show(False, 100.0))
        self.assertFalse(gate.armed)


if __name__ == "__main__":
    unittest.main()
