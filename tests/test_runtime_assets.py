import unittest

from asset_manager import ASSET_DIR, ROLE_FILES, resolve_asset, role_for_dialogue, role_for_work_mode


class RuntimeAssetTests(unittest.TestCase):
    def test_every_character_role_resolves_to_committed_file(self):
        for role in ROLE_FILES:
            with self.subTest(role=role):
                path = resolve_asset(role)
                self.assertIsNotNone(path)
                self.assertTrue(path.is_file())
                self.assertEqual(path.parent, ASSET_DIR)

    def test_canonical_png_names(self):
        expected = {
            "default": "main_kyunghee.png",
            "cheer": "focus_cheer_kyunghee.png",
            "rest": "rest_suggest_kyunghee.png",
            "away": "away_kyunghee.png",
            "worry": "warning_kyunghee.png",
            "nag": "warning_kyunghee.png",
            "praise": "leave_work_kyunghee.png",
            "stats": "stats_kyunghee.png",
            "settings": "settings_kyunghee.png",
            "alert": "alert_kyunghee.png",
            "master_face": "profile_kyunghee.png",
        }
        for role, filename in expected.items():
            with self.subTest(role=role):
                self.assertEqual(ROLE_FILES[role][0], filename)

    def test_canonical_assets_are_installed(self):
        for role, filenames in ROLE_FILES.items():
            with self.subTest(role=role):
                self.assertEqual(resolve_asset(role).name, filenames[0])

    def test_workday_visual_policy(self):
        self.assertEqual(role_for_work_mode("normal"), "default")
        self.assertEqual(role_for_work_mode("wind_down"), "rest")
        self.assertEqual(role_for_work_mode("leave"), "praise")
        self.assertEqual(role_for_work_mode("strong_leave"), "nag")
        self.assertEqual(role_for_work_mode("late_leave"), "nag")
        self.assertEqual(role_for_work_mode("hard_stop"), "nag")

    def test_dialogue_visual_policy(self):
        self.assertEqual(role_for_dialogue("return"), "cute_cheer")
        self.assertEqual(role_for_dialogue("away_start"), "away")
        self.assertEqual(role_for_dialogue("snooze1"), "rest")
        self.assertEqual(role_for_dialogue("snooze2"), "nag")
        self.assertEqual(role_for_dialogue("stats"), "stats")
        self.assertEqual(role_for_dialogue("break", "leave"), "praise")


if __name__ == "__main__":
    unittest.main()
