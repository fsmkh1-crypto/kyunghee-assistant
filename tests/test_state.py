import json
import tempfile
import unittest
from pathlib import Path

from state import (
    DailyStats,
    PersistedState,
    SessionState,
    load_state,
    prepare_startup_state,
    reset_untracked_session,
    rollover_daily,
    save_state,
)


class StateTests(unittest.TestCase):
    def test_midnight_keeps_global_session_but_resets_today_portion(self):
        state = PersistedState(
            6,
            DailyStats(
                day="2026-09-02",
                active_seconds=10_000,
                longest_continuous_today=3_000,
            ),
            SessionState(
                continuous_seconds=4_000,
                day_continuous_seconds=2_000,
                next_break_at=4_500,
            ),
        )
        rollover_daily(state, today="2026-09-03")
        self.assertEqual(state.daily.day, "2026-09-03")
        self.assertEqual(state.daily.active_seconds, 0)
        self.assertEqual(state.daily.longest_continuous_today, 0)
        self.assertEqual(state.session.continuous_seconds, 4_000)
        self.assertEqual(state.session.day_continuous_seconds, 0)
        self.assertEqual(state.session.next_break_at, 4_500)

    def test_midnight_clears_daily_break_suppression(self):
        state = PersistedState(
            7,
            DailyStats(day="2026-09-02", break_reminders_suppressed=True),
            SessionState(continuous_seconds=1200),
        )
        rollover_daily(state, today="2026-09-03")
        self.assertEqual(state.daily.day, "2026-09-03")
        self.assertFalse(state.daily.break_reminders_suppressed)
        self.assertEqual(state.session.continuous_seconds, 1200)

    def test_break_suppression_roundtrips_in_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            state = PersistedState(
                7,
                DailyStats(day="2026-09-04", break_reminders_suppressed=True),
                SessionState(),
            )
            save_state(path, state, now_wall=1000)
            loaded = load_state(path)
            self.assertTrue(loaded.daily.break_reminders_suppressed)

    def test_midnight_away_is_counted_as_one_ongoing_away(self):
        state = PersistedState(
            6,
            DailyStats(day="2026-09-02", away_count=3),
            SessionState(is_away=True, away_started_wall=123.0, away_started_mono=456.0),
        )
        rollover_daily(state, today="2026-09-03")
        self.assertEqual(state.daily.away_count, 1)
        self.assertTrue(state.session.is_away)

    def test_restart_after_long_downtime_resets_session_only(self):
        state = PersistedState(
            6,
            DailyStats(day="2026-09-02", active_seconds=5_000),
            SessionState(
                continuous_seconds=3_500,
                next_break_at=3_600,
                idle_candidate_seconds=200,
                last_seen_wall=1_000,
            ),
        )
        gap = reset_untracked_session(state, now_wall=1_120, tolerance_sec=60)
        self.assertEqual(gap, 120)
        self.assertEqual(state.session.continuous_seconds, 0)
        self.assertEqual(state.session.idle_candidate_seconds, 0)
        self.assertEqual(state.daily.active_seconds, 5_000)

    def test_restart_within_tolerance_preserves_session_and_idle_candidate(self):
        state = PersistedState(
            6,
            DailyStats(day="2026-09-02"),
            SessionState(
                continuous_seconds=100,
                idle_candidate_seconds=40,
                last_seen_wall=1_000,
            ),
        )
        reset_untracked_session(state, now_wall=1_030, tolerance_sec=60)
        self.assertEqual(state.session.continuous_seconds, 100)
        self.assertEqual(state.session.idle_candidate_seconds, 40)

    def test_startup_resets_stale_away_before_new_day_rollover(self):
        state = PersistedState(
            6,
            DailyStats(day="2026-09-02", away_count=5),
            SessionState(is_away=True, manual_away=True, last_seen_wall=1_000),
        )
        prepare_startup_state(
            state,
            now_wall=1_120,
            today="2026-09-03",
            tolerance_sec=60,
        )
        self.assertEqual(state.daily.day, "2026-09-03")
        self.assertEqual(state.daily.away_count, 0)
        self.assertFalse(state.session.is_away)

    def test_bad_json_is_preserved_as_corrupt_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            path.write_text("{ definitely broken", encoding="utf-8")
            state = load_state(path)
            self.assertEqual(state.session.continuous_seconds, 0)
            self.assertFalse(path.exists())
            self.assertTrue(list(Path(td).glob("state.json.*.corrupt")))

    def test_unknown_fields_and_bad_types_do_not_break_load(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            path.write_text(
                json.dumps({
                    "schema_version": 999,
                    "daily": {
                        "day": "2026-09-02",
                        "active_seconds": "12.5",
                        "away_count": "2",
                        "future_field": "ignored",
                    },
                    "session": {
                        "continuous_seconds": "bad",
                        "manual_away": "false",
                        "idle_candidate_seconds": "42.5",
                        "future_field": 123,
                    },
                }),
                encoding="utf-8",
            )
            state = load_state(path)
            self.assertEqual(state.daily.active_seconds, 12.5)
            self.assertEqual(state.daily.away_count, 2)
            self.assertEqual(state.session.continuous_seconds, 0)
            self.assertFalse(state.session.manual_away)
            self.assertEqual(state.session.idle_candidate_seconds, 42.5)

    def test_save_is_readable_and_updates_last_seen_and_candidate(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            state = PersistedState(
                6,
                DailyStats(day="2026-09-02"),
                SessionState(idle_candidate_seconds=123.0),
            )
            save_state(path, state, now_wall=1234.5)
            loaded = load_state(path)
            self.assertEqual(loaded.session.last_seen_wall, 1234.5)
            self.assertEqual(loaded.session.idle_candidate_seconds, 123.0)


if __name__ == "__main__":
    unittest.main()
