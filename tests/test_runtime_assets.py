import unittest
from pathlib import Path

from asset_manager import (
    ASSET_DIR,
    ROLE_FILES,
    VARIANT_ROLE,
    available_complete_sets,
    resolve_asset,
    role_for_dialogue,
    role_for_work_mode,
    select_session_set,
)


class RuntimeAssetTests(unittest.TestCase):
    def test_every_character_role_resolves_to_committed_file(self):
        for role in ROLE_FILES:
            with self.subTest(role=role):
                path = resolve_asset(role)
                self.assertIsNotNone(path)
                self.assertTrue(path.is_file())
                self.assertTrue(path.is_relative_to(ASSET_DIR))
                self.assertNotEqual(path.parent, ASSET_DIR)

    def test_role_folders_keep_canonical_fallback_assets(self):
        expected = {
            "default": "default/main_kyunghee.png",
            "cheer": "cheer/focus_cheer_kyunghee.png",
            "rest": "rest/rest_suggest_kyunghee.png",
            "away": "away/away_kyunghee.png",
            "worry": "warning/warning_kyunghee.png",
            "nag": "warning/warning_kyunghee.png",
            "praise": "leave/leave_work_kyunghee.png",
            "stats": "stats/stats_kyunghee.png",
            "settings": "settings/settings_kyunghee.png",
            "alert": "alert/alert_kyunghee.png",
            "master_face": "profile/profile_kyunghee.png",
        }
        for role, relative in expected.items():
            with self.subTest(role=role):
                self.assertEqual(ROLE_FILES[role][0], relative)
                self.assertTrue((ASSET_DIR / relative).is_file())

    def test_numbered_runtime_assets_use_one_complete_set(self):
        complete = available_complete_sets()
        self.assertTrue(complete)
        selected = select_session_set()
        self.assertIn(selected, complete)
        for role in ROLE_FILES:
            with self.subTest(role=role):
                variant_role = VARIANT_ROLE[role]
                expected = ASSET_DIR / variant_role / f"{variant_role}_{selected:02d}.png"
                self.assertEqual(resolve_asset(role), expected)

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
