import unittest
from state import PersistedState, DailyStats, SessionState
from timer_engine import TimerEngine, SNOOZE_SEC, GAP_TOLERANCE_SEC

class FakeEnv:
    def __init__(self):
        self.mono = 0.0
        self.wall = 1000000.0
        self.idle = 0.0
        self.tick = 1
    def clock(self): return self.mono
    def wall_clock(self): return self.wall
    def idle_provider(self): return self.idle, self.tick
    def advance(self, sec, idle=None, input_event=False):
        self.mono += sec
        self.wall += sec
        if idle is None: self.idle += sec
        else: self.idle = idle
        if input_event:
            self.tick += 1
            self.idle = 0.0

def new_state():
    return PersistedState(4, DailyStats(day="2026-09-02"), SessionState())

class TimerEngineTests(unittest.TestCase):
    def make(self):
        e = FakeEnv(); s = new_state()
        eng = TimerEngine(s, clock=e.clock, wall=e.wall_clock, idle_provider=e.idle_provider)
        return e, s, eng

    def test_break_at_60_minutes(self):
        e,s,eng = self.make()
        s.session.continuous_seconds = 3598
        e.advance(1, idle=0)
        self.assertFalse(eng.tick().break_due)
        e.advance(1, idle=0)
        self.assertTrue(eng.tick().break_due)

    def test_snooze_is_exactly_five_minutes(self):
        e,s,eng = self.make(); s.session.continuous_seconds = 3600
        eng.snooze_break()
        self.assertEqual(s.session.next_break_at, 3900)

    def test_manual_away_does_not_resume_from_start_click(self):
        e,s,eng = self.make(); eng.start_manual_away()
        e.advance(1, idle=1); r = eng.tick()
        self.assertTrue(s.session.manual_away)
        self.assertFalse(r.became_active)

    def test_manual_away_resumes_on_later_input(self):
        e,s,eng = self.make(); eng.start_manual_away()
        e.advance(4, input_event=True); r = eng.tick()
        self.assertTrue(r.became_active)
        self.assertFalse(s.session.manual_away)
        self.assertAlmostEqual(s.daily.manual_away_seconds, 4)

    def test_long_gap_is_away_even_if_wake_input_resets_idle(self):
        e,s,eng = self.make()
        e.advance(GAP_TOLERANCE_SEC + 10, input_event=True); r = eng.tick()
        self.assertTrue(r.long_gap)
        self.assertEqual(s.daily.active_seconds, 0)
        self.assertGreater(s.daily.away_seconds, GAP_TOLERANCE_SEC)

    def test_repeated_snooze(self):
        e,s,eng = self.make(); s.session.continuous_seconds = 3600
        eng.snooze_break(); first = s.session.next_break_at
        s.session.continuous_seconds = first; eng.snooze_break()
        self.assertEqual(s.session.next_break_at, first + SNOOZE_SEC)

if __name__ == "__main__":
    unittest.main()
