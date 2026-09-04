import tempfile
import unittest
from pathlib import Path

from asset_manager import resolve_asset, role_for_dialogue, role_for_work_mode


class AssetManagerTests(unittest.TestCase):
    def test_work_modes_map_to_expected_character_roles(self):
        self.assertEqual(role_for_work_mode("normal"), "default")
        self.assertEqual(role_for_work_mode("wind_down"), "rest")
        self.assertEqual(role_for_work_mode("leave"), "praise")
        self.assertEqual(role_for_work_mode("late_leave"), "nag")
        self.assertEqual(role_for_work_mode("hard_stop"), "nag")

    def test_dialogue_role_respects_leave_mode(self):
        self.assertEqual(role_for_dialogue("cheer", "normal"), "cheer")
        self.assertEqual(role_for_dialogue("away_start", "normal"), "away")
        self.assertEqual(role_for_dialogue("break", "normal"), "rest")
        self.assertEqual(role_for_dialogue("stats", "normal"), "stats")
        self.assertEqual(role_for_dialogue("cheer", "leave"), "praise")
        self.assertEqual(role_for_dialogue("playful", "late_leave"), "nag")

    def test_resolver_prefers_canonical_png_but_accepts_legacy(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "nag.jpg").write_bytes(b"x")
            self.assertEqual(resolve_asset("nag", root), root / "nag.jpg")
            (root / "warning").mkdir()
            (root / "warning" / "warning_kyunghee.png").write_bytes(b"x")
            self.assertEqual(resolve_asset("nag", root), root / "warning" / "warning_kyunghee.png")

    def test_missing_asset_is_safe(self):
        with tempfile.TemporaryDirectory() as td:
            self.assertIsNone(resolve_asset("default", Path(td)))


if __name__ == "__main__":
    unittest.main()
