import unittest

from messages import (
    RARE_MIN_GAP,
    RARE_POOLS,
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


if __name__ == "__main__":
    unittest.main()
