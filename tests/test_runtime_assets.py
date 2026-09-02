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

    def test_runtime_character_roles_prefer_webp(self):
        roles = {"default", "playful", "cheer", "cute_cheer", "nag", "worry", "praise"}
        for role in roles:
            with self.subTest(role=role):
                self.assertEqual(resolve_asset(role).suffix.lower(), ".webp")

    def test_master_face_prefers_lossless_png(self):
        self.assertEqual(resolve_asset("master_face").name, "master_face.png")

    def test_workday_visual_policy(self):
        self.assertEqual(role_for_work_mode("normal"), "default")
        self.assertEqual(role_for_work_mode("wind_down"), "worry")
        self.assertEqual(role_for_work_mode("leave"), "praise")
        self.assertEqual(role_for_work_mode("strong_leave"), "nag")
        self.assertEqual(role_for_work_mode("late_leave"), "nag")
        self.assertEqual(role_for_work_mode("hard_stop"), "nag")

    def test_dialogue_visual_policy(self):
        self.assertEqual(role_for_dialogue("return"), "cute_cheer")
        self.assertEqual(role_for_dialogue("snooze1"), "worry")
        self.assertEqual(role_for_dialogue("snooze2"), "nag")
        self.assertEqual(role_for_dialogue("break", "leave"), "praise")


if __name__ == "__main__":
    unittest.main()
