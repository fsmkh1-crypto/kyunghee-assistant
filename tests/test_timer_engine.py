import unittest

from state import DailyStats, PersistedState, SessionState
from timer_engine import (
    BREAK_INTERVAL_SEC,
    GAP_TOLERANCE_SEC,
    IDLE_THRESHOLD_SEC,
    SNOOZE_SEC,
    TimerEngine,
)


class FakeEnv:
    def __init__(self):
        self.mono = 0.0
        self.wall = 1_000_000.0
        self.idle = 0.0
        self.tick = 1

    def clock(self):
        return self.mono

    def wall_clock(self):
        return self.wall

    def idle_provider(self):
        return self.idle, self.tick

    def advance(self, sec, idle=None, input_event=False, wall_delta=None):
        self.mono += sec
        self.wall += sec if wall_delta is None else wall_delta
        if idle is None:
            self.idle += sec
        else:
            self.idle = idle
        if input_event:
            self.tick += 1
            self.idle = 0.0


def new_state():
    return PersistedState(5, DailyStats(day="2026-09-02"), SessionState())


class TimerEngineTests(unittest.TestCase):
    def make(self):
        env = FakeEnv()
        state = new_state()
        engine = TimerEngine(
            state,
            clock=env.clock,
            wall=env.wall_clock,
            idle_provider=env.idle_provider,
        )
        return env, state, engine

    def test_break_at_60_minutes(self):
        e, s, eng = self.make()
        s.session.continuous_seconds = 3598
        s.session.day_continuous_seconds = 3598
        e.advance(1, idle=0, input_event=True)
        self.assertFalse(eng.tick().break_due)
        e.advance(1, idle=0, input_event=True)
        self.assertTrue(eng.tick().break_due)

    def test_snooze_is_exactly_five_minutes(self):
        _, s, eng = self.make()
        s.session.continuous_seconds = 3600
        eng.snooze_break()
        self.assertEqual(s.session.next_break_at, 3900)

    def test_repeated_snooze_is_always_five_minutes(self):
        _, s, eng = self.make()
        s.session.continuous_seconds = 3600
        for _ in range(3):
            eng.snooze_break()
            expected = s.session.continuous_seconds + SNOOZE_SEC
            self.assertEqual(s.session.next_break_at, expected)
            s.session.continuous_seconds = expected

    def test_manual_away_does_not_resume_from_start_click(self):
        e, s, eng = self.make()
        eng.start_manual_away()
        e.advance(1, idle=1)
        result = eng.tick()
        self.assertTrue(s.session.manual_away)
        self.assertFalse(result.became_active)

    def test_manual_away_resumes_on_later_input_and_resume_tick_is_away(self):
        e, s, eng = self.make()
        eng.start_manual_away()
        e.advance(4, input_event=True)
        result = eng.tick()
        self.assertTrue(result.became_active)
        self.assertTrue(result.manual_resumed_by_input)
        self.assertFalse(s.session.manual_away)
        self.assertAlmostEqual(s.daily.manual_away_seconds, 4)
        self.assertEqual(s.daily.active_seconds, 0)

    def test_long_gap_is_away_even_if_wake_input_resets_idle(self):
        e, s, eng = self.make()
        gap = GAP_TOLERANCE_SEC + 10
        e.advance(gap, input_event=True)
        result = eng.tick()
        self.assertTrue(result.long_gap)
        self.assertTrue(result.became_active)
        self.assertEqual(s.daily.active_seconds, 0)
        self.assertAlmostEqual(s.daily.away_seconds, gap)
        self.assertEqual(s.session.continuous_seconds, 0)

    def test_manual_away_sleep_gap_remains_manual_away_time(self):
        e, s, eng = self.make()
        eng.start_manual_away()
        gap = GAP_TOLERANCE_SEC + 500
        e.advance(gap, input_event=True)
        result = eng.tick()
        self.assertTrue(result.long_gap)
        self.assertTrue(result.became_active)
        self.assertAlmostEqual(s.daily.manual_away_seconds, gap)
        self.assertEqual(s.daily.active_seconds, 0)

    def test_long_gap_without_return_input_remains_away(self):
        e, s, eng = self.make()
        gap = GAP_TOLERANCE_SEC + 50
        e.advance(gap, idle=gap, input_event=False)
        result = eng.tick()
        self.assertTrue(result.long_gap)
        self.assertTrue(result.became_away)
        self.assertTrue(s.session.is_away)
        self.assertFalse(result.became_active)

    def test_five_minute_idle_retroactively_becomes_away(self):
        e, s, eng = self.make()
        # Four minutes fifty-nine seconds are provisionally active.
        for _ in range(IDLE_THRESHOLD_SEC - 1):
            e.advance(1)
            eng.tick()
        self.assertEqual(int(s.daily.active_seconds), IDLE_THRESHOLD_SEC - 1)

        # At five minutes, the entire no-input interval is reclassified.
        e.advance(1)
        result = eng.tick()
        self.assertTrue(result.became_away)
        self.assertEqual(int(s.daily.active_seconds), 0)
        self.assertEqual(int(s.daily.away_seconds), IDLE_THRESHOLD_SEC)
        self.assertEqual(s.session.continuous_seconds, 0)

    def test_short_idle_confirmed_by_input_stays_active(self):
        e, s, eng = self.make()
        for _ in range(240):
            e.advance(1)
            eng.tick()
        e.advance(1, input_event=True)
        eng.tick()
        self.assertEqual(int(s.daily.active_seconds), 241)
        self.assertEqual(s.daily.away_seconds, 0)
        self.assertGreaterEqual(s.daily.longest_continuous_today, 241)

    def test_auto_away_return_tick_is_not_active(self):
        e, s, eng = self.make()
        for _ in range(IDLE_THRESHOLD_SEC):
            e.advance(1)
            eng.tick()
        before_away = s.daily.away_seconds
        e.advance(1, input_event=True)
        result = eng.tick()
        self.assertTrue(result.became_active)
        self.assertEqual(s.daily.active_seconds, 0)
        self.assertEqual(s.daily.away_seconds, before_away + 1)
        self.assertEqual(s.session.continuous_seconds, 0)

    def test_wall_clock_jump_does_not_create_fake_active_time(self):
        e, s, eng = self.make()
        e.advance(1, idle=0, input_event=True, wall_delta=3600)
        eng.tick()
        self.assertAlmostEqual(s.daily.active_seconds, 1)

    def test_manual_away_ends_continuous_session(self):
        _, s, eng = self.make()
        s.session.continuous_seconds = 1800
        s.session.day_continuous_seconds = 1800
        eng.start_manual_away()
        self.assertEqual(s.session.continuous_seconds, 0)
        self.assertEqual(s.session.next_break_at, BREAK_INTERVAL_SEC)
        self.assertGreaterEqual(s.daily.longest_continuous_today, 1800)


if __name__ == "__main__":
    unittest.main()
