import unittest

from messages import (
    DAILY_TEMPERAMENT_POOLS,
    RARE_MIN_GAP,
    RARE_POOLS,
    custom_dialogue_lines,
    daily_temperament,
    habit_dialogue_kind,
    maybe_pick_custom,
    maybe_pick_daily_temperament,
    _reset_rare_state_for_tests,
    maybe_pick_rare,
    time_of_day_kind,
)


class MessageBehaviorTests(unittest.TestCase):
    def tearDown(self):
        _reset_rare_state_for_tests()

    def test_time_of_day_boundaries(self):
        self.assertEqual(time_of_day_kind(6), "morning")
        self.assertEqual(time_of_day_kind(11), "lunch")
        self.assertEqual(time_of_day_kind(14), "afternoon")
        self.assertEqual(time_of_day_kind(17), "evening")
        self.assertEqual(time_of_day_kind(21), "late")

    def test_daily_temperament_is_stable_for_same_date(self):
        first = daily_temperament("2026-09-04")
        self.assertEqual(first, daily_temperament("2026-09-04"))
        self.assertIn(first, DAILY_TEMPERAMENT_POOLS)

    def test_daily_temperament_respects_chance(self):
        self.assertIsNone(maybe_pick_daily_temperament("2026-09-04", chance=0.18, roll=0.9))
        selected = maybe_pick_daily_temperament("2026-09-04", chance=1.0, roll=0.0)
        mood = daily_temperament("2026-09-04")
        self.assertIn(selected, DAILY_TEMPERAMENT_POOLS[mood])

    def test_rare_dialogue_respects_minimum_gap(self):
        _reset_rare_state_for_tests(0)
        for _ in range(RARE_MIN_GAP - 1):
            self.assertIsNone(maybe_pick_rare("balanced", chance=1.0, roll=0.0))
        self.assertIn(maybe_pick_rare("balanced", chance=1.0, roll=0.0), RARE_POOLS["balanced"])

    def test_rare_dialogue_respects_chance(self):
        _reset_rare_state_for_tests()
        self.assertIsNone(maybe_pick_rare("balanced", chance=0.04, roll=0.5))
        self.assertIn(maybe_pick_rare("balanced", chance=0.04, roll=0.0), RARE_POOLS["balanced"])

    def test_unknown_personality_falls_back_to_balanced(self):
        _reset_rare_state_for_tests()
        self.assertIn(maybe_pick_rare("unknown", chance=1.0, roll=0.0), RARE_POOLS["balanced"])

    def test_custom_dialogue_selection(self):
        value = "첫 문장\n둘째 문장"
        self.assertEqual(custom_dialogue_lines(value), ["첫 문장", "둘째 문장"])
        self.assertIsNone(maybe_pick_custom(value, chance=0.25, roll=0.9))
        self.assertIn(maybe_pick_custom(value, chance=0.25, roll=0.0), {"첫 문장", "둘째 문장"})

    def test_habit_dialogue_priorities(self):
        self.assertEqual(
            habit_dialogue_kind(away_count=5, longest_continuous=2000, continuous_seconds=4600),
            "nag",
        )
        self.assertEqual(
            habit_dialogue_kind(away_count=3, longest_continuous=4000, continuous_seconds=1200),
            "praise",
        )
        self.assertEqual(
            habit_dialogue_kind(away_count=1, longest_continuous=5000, continuous_seconds=3100),
            "worry",
        )
        self.assertIsNone(
            habit_dialogue_kind(away_count=1, longest_continuous=1800, continuous_seconds=1200)
        )


if __name__ == "__main__":
    unittest.main()
