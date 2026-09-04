import unittest

from messages import PERSONALITY_POOLS, pick, time_of_day_kind


class MessageTests(unittest.TestCase):
    def test_time_buckets(self):
        self.assertEqual(time_of_day_kind(8), "morning")
        self.assertEqual(time_of_day_kind(12), "lunch")
        self.assertEqual(time_of_day_kind(15), "afternoon")
        self.assertEqual(time_of_day_kind(18), "evening")
        self.assertEqual(time_of_day_kind(23), "late")
        self.assertEqual(time_of_day_kind(3), "late")

    def test_personality_pool_is_used_when_available(self):
        for personality in ("warm", "playful", "strict"):
            with self.subTest(personality=personality):
                value = pick("click", personality=personality)
                self.assertIn(value, PERSONALITY_POOLS[personality]["click"])

    def test_unknown_personality_falls_back_to_base_pool(self):
        value = pick("morning", personality="unknown")
        self.assertIsInstance(value, str)
        self.assertTrue(value)


if __name__ == "__main__":
    unittest.main()
