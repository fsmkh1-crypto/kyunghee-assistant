import unittest

from state import DailyStats, PersistedState, SessionState
from stats_summary import recent_daily_stats, stats_reaction, summarize_recent


class StatsSummaryTests(unittest.TestCase):
    def _state(self):
        return PersistedState(
            8,
            DailyStats(
                day="2026-09-05",
                active_seconds=7200,
                away_seconds=1800,
                away_count=2,
                longest_continuous_today=3600,
            ),
            SessionState(),
            history=[
                DailyStats(day="2026-09-03", active_seconds=3600, away_seconds=600, away_count=1),
                DailyStats(day="2026-09-04", active_seconds=5400, away_seconds=600, away_count=1, longest_continuous_today=2400),
            ],
        )

    def test_recent_window_is_calendar_aligned_and_fills_missing_days(self):
        rows = recent_daily_stats(self._state(), days=4, today="2026-09-05")
        self.assertEqual([row.day for row in rows], [
            "2026-09-02", "2026-09-03", "2026-09-04", "2026-09-05"
        ])
        self.assertEqual(rows[0].active_seconds, 0)
        self.assertEqual(rows[-1].active_seconds, 7200)

    def test_summary_uses_tracked_day_average_and_current_day(self):
        summary = summarize_recent(self._state(), days=7, today="2026-09-05")
        self.assertEqual(summary.tracked_days, 3)
        self.assertEqual(summary.active_seconds, 16200)
        self.assertEqual(summary.away_seconds, 3000)
        self.assertEqual(summary.away_count, 4)
        self.assertEqual(summary.average_active_seconds, 5400)
        self.assertEqual(summary.best_day, "2026-09-05")
        self.assertEqual(summary.best_day_active_seconds, 7200)
        self.assertAlmostEqual(summary.active_ratio, 84.375)

    def test_current_day_overrides_same_day_history_entry(self):
        state = self._state()
        state.history.append(DailyStats(day="2026-09-05", active_seconds=999999))
        summary = summarize_recent(state, days=1, today="2026-09-05")
        self.assertEqual(summary.active_seconds, 7200)

    def test_reaction_is_safe_when_empty(self):
        state = PersistedState(8, DailyStats(day="2026-09-05"), SessionState())
        text = stats_reaction(summarize_recent(state, today="2026-09-05"))
        self.assertIn("기록", text)


if __name__ == "__main__":
    unittest.main()
