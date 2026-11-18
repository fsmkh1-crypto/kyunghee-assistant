"""Calendar accounting regressions; fake clocks and temporary profiles only."""
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from state import DailyStats, PersistedState, SessionState, load_state, save_state, prepare_startup_state
from timer_engine import TimerEngine


class Clock:
    def __init__(self, hour=23, minute=57, second=0):
        self.wall = datetime(2026, 11, 16, hour, minute, second).timestamp()
        self.mono = 0
        self.idle = 0
        self.input = 1

    def engine(self, state):
        return TimerEngine(state, clock=lambda: self.mono, wall=lambda: self.wall,
                           idle_provider=lambda: (self.idle, self.input))

    def tick(self, engine, seconds=1, input=False, mono=None):
        self.wall += seconds
        self.mono += seconds if mono is None else mono
        self.idle += seconds
        if input:
            self.input += 1
            self.idle = 0
        return engine.tick()


class MidnightAccountingTests(unittest.TestCase):
    def make(self, **kw):
        clock = Clock(**kw)
        state = PersistedState(8, DailyStats(day='2026-11-16'), SessionState())
        return clock, state, clock.engine(state)

    def assert_days(self, state, active, away, manual=None, counts=None):
        days = [*state.history, state.daily]
        self.assertEqual([d.active_seconds for d in days], active)
        self.assertEqual([d.away_seconds for d in days], away)
        for d in days:
            self.assertEqual(d.away_seconds, d.manual_away_seconds + d.auto_away_seconds)
        if manual is not None:
            self.assertEqual([d.manual_away_seconds for d in days], manual)
        if counts is not None:
            self.assertEqual([d.away_count for d in days], counts)

    def test_sleep_crosses_midnight_with_and_without_return(self):
        for resume in (False, True):
            for paused_clock in (False, True):
                with self.subTest(resume=resume, paused_clock=paused_clock):
                    c, s, e = self.make(hour=23, minute=0)
                    r = c.tick(e, 7200, input=resume, mono=1 if paused_clock else None)
                    self.assertTrue(r.long_gap)
                    self.assertEqual(r.became_active, resume)
                    self.assert_days(s, [0, 0], [3600, 3600], [0, 0], [1, 1])
                    self.assertEqual(r.away_duration if resume else e.current_away_duration(), 7200)

    def test_manual_break_sleep_crosses_midnight(self):
        c, s, e = self.make(hour=23, minute=0)
        e.accept_break()
        c.tick(e, 7200)
        self.assert_days(s, [0, 0], [3600, 3600], [3600, 3600], [1, 1])
        self.assertEqual(e.current_away_duration(), 7200)

    def test_auto_idle_reclassifies_previous_day(self):
        c, s, e = self.make()
        for _ in range(300):
            c.tick(e)
        self.assert_days(s, [0, 0], [180, 120], [0, 0], [1, 1])
        self.assertEqual(e.current_away_duration(), 300)
        self.assertEqual([d.longest_continuous_today for d in [*s.history, s.daily]], [0, 0])
        c.tick(e, input=True)
        self.assert_days(s, [0, 0], [180, 121], counts=[1, 1])

    def test_existing_focus_longest_is_preserved_on_idle_reclassification(self):
        c, s, e = self.make(hour=23, minute=55)
        for _ in range(120):
            c.tick(e, input=True)
        for _ in range(300):
            c.tick(e)
        self.assert_days(s, [120, 0], [180, 120], counts=[1, 1])
        self.assertEqual(s.history[0].longest_continuous_today, 120)

    def test_short_idle_input_confirms_prior_day_longest(self):
        c, s, e = self.make()
        for _ in range(240):
            c.tick(e)
        c.tick(e, input=True)
        self.assert_days(s, [180, 61], [0, 0])
        self.assertEqual(s.history[0].longest_continuous_today, 180)
        self.assertEqual(s.daily.longest_continuous_today, 61)
        self.assertEqual(s.session.continuous_seconds, 241)

    def test_manual_break_confirms_pending_previous_day(self):
        c, s, e = self.make()
        for _ in range(240):
            c.tick(e)
        e.accept_break()
        self.assertEqual(s.history[0].longest_continuous_today, 180)
        self.assertEqual(s.daily.longest_continuous_today, 60)

    def test_active_tick_splits_at_exact_midnight_and_keeps_break_schedule(self):
        c, s, e = self.make(hour=23, minute=59, second=30)
        s.daily.break_reminders_suppressed = True
        s.session.continuous_seconds = 3550
        c.tick(e, 30, input=True)
        self.assert_days(s, [30, 0], [0, 0])
        self.assertEqual(s.session.day_continuous_seconds, 0)
        self.assertFalse(s.daily.break_reminders_suppressed)
        self.assertTrue(s.history[0].break_reminders_suppressed)
        self.assertTrue(c.tick(e, 20, input=True).break_due)
        self.assert_days(s, [30, 20], [0, 0])

    def test_tick_spanning_midnight_not_just_landing_on_it(self):
        c, s, e = self.make(hour=23, minute=59, second=30)
        c.tick(e, 60, input=True)
        self.assert_days(s, [30, 30], [0, 0])
        self.assertEqual(s.session.continuous_seconds, 60)
        self.assertEqual(s.daily.longest_continuous_today, 30)
        self.assertEqual(s.history[0].longest_continuous_today, 30)

    def test_auto_away_at_exact_midnight(self):
        c, s, e = self.make(hour=23, minute=55)
        for _ in range(300):
            c.tick(e)
        self.assert_days(s, [0, 0], [300, 0], counts=[1, 1])
        self.assertEqual(e.current_away_duration(), 300)

    def test_manual_break_regular_ticks_cross_midnight(self):
        c, s, e = self.make()
        e.accept_break()
        for _ in range(300):
            c.tick(e)
        self.assert_days(s, [0, 0], [180, 120], [180, 120], [1, 1])

    def test_pending_days_roundtrip_and_reclassify_after_restart(self):
        c, s, e = self.make()
        for _ in range(240):
            c.tick(e)
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'state.json'
            save_state(path, s, now_wall=c.wall)
            s = load_state(path)
            prepare_startup_state(s, c.wall, today='2026-11-17')
        e = c.engine(s)
        for _ in range(60):
            c.tick(e)
        self.assert_days(s, [0, 0], [180, 120], counts=[1, 1])
        self.assertEqual(e.current_away_duration(), 300)

    def test_quick_restart_at_midnight_preserves_yesterdays_pending_tail(self):
        c, s, e = self.make()
        for _ in range(179):
            c.tick(e)
        c.wall += 1
        c.mono += 1
        c.idle += 1
        # Save then startup with one untracked second. Do not invent downtime.
        s.session.last_seen_wall = c.wall - 1
        prepare_startup_state(s, c.wall, today='2026-11-17')
        e = c.engine(s)
        for _ in range(120):
            c.tick(e)
        self.assert_days(s, [0, 0], [179, 120], counts=[1, 1])

    def test_multi_day_gap_preserves_total_and_each_date(self):
        c, s, e = self.make(hour=23, minute=0)
        c.tick(e, 26 * 3600)
        self.assert_days(s, [0, 0, 0], [3600, 86400, 3600], counts=[1, 1, 1])


    def test_wall_only_multi_day_sleep_caps_total_but_assigns_recent_days(self):
        c, s, e = self.make(hour=23, minute=0)
        c.tick(e, 74 * 3600, mono=1)
        self.assertEqual(s.daily.day, '2026-11-20')
        self.assertEqual(sum(d.away_seconds for d in [*s.history, s.daily]), 86400)
        self.assertEqual(s.daily.away_seconds, 3600)
        self.assertEqual(s.history[-1].day, '2026-11-19')
        self.assertEqual(s.history[-1].away_seconds, 23 * 3600)
        self.assertEqual(s.history[0].away_seconds, 0)
        self.assertEqual(s.history[0].away_count, 0)
        self.assertEqual(s.history[-1].away_count, 1)
        self.assertEqual(s.daily.away_count, 1)


    def test_backward_wall_clock_does_not_rewrite_archived_day(self):
        c, s, e = self.make(hour=23, minute=59, second=59)
        c.tick(e, input=True)
        old_active = s.history[0].active_seconds
        c.wall -= 60
        c.tick(e, input=True)
        self.assertEqual(s.history[0].active_seconds, old_active)
        self.assertEqual(s.daily.active_seconds, 1)
        self.assertEqual(s.daily.day, '2026-11-17')


    def test_constructor_closes_startup_midnight_race_without_downtime(self):
        c, s, e = self.make(hour=23, minute=59, second=59)
        s.daily.active_seconds = 123
        c.wall += 2
        e = c.engine(s)
        self.assert_days(s, [123, 0], [0, 0])
        c.tick(e, input=True)
        self.assert_days(s, [123, 1], [0, 0])


    def test_crossing_midnight_again_after_rollback_never_rewrites_history(self):
        for away in (False, True):
            with self.subTest(away=away):
                c, s, e = self.make(hour=23, minute=59, second=59)
                if away:
                    e.accept_break()
                c.tick(e, input=not away)
                old = (s.history[0].active_seconds, s.history[0].away_seconds)
                c.wall -= 3
                for _ in range(5):
                    c.tick(e, input=not away)
                self.assertEqual((s.history[0].active_seconds, s.history[0].away_seconds), old)
                self.assertEqual(s.daily.away_seconds if away else s.daily.active_seconds, 5)
                self.assertEqual(s.daily.day, '2026-11-17')


if __name__ == '__main__':
    unittest.main()
