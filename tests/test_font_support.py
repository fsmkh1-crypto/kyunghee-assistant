import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import font_support


class FontSupportTests(unittest.TestCase):
    def test_semantic_weights_use_real_windows_faces(self):
        root = SimpleNamespace()
        with patch.object(font_support.tkfont, "families", return_value=(
            "Pretendard", "Pretendard Medium", "Pretendard SemiBold", "Malgun Gothic",
        )):
            self.assertEqual(font_support.ui_font(root, 13), ("Pretendard", 13, "normal"))
            self.assertEqual(font_support.ui_font(root, 10, "controls"), ("Pretendard Medium", 10, "normal"))
            self.assertEqual(font_support.ui_font(root, 20, "timer"), ("Pretendard SemiBold", 20, "normal"))
            self.assertEqual(font_support.ui_font(root, 12, weight="bold"), ("Pretendard SemiBold", 12, "normal"))

    def test_missing_pretendard_uses_known_korean_fallback_and_keeps_bold(self):
        with patch.object(font_support.tkfont, "families", return_value=("Arial", "Malgun Gothic")):
            self.assertEqual(font_support.ui_font(SimpleNamespace(), 13), ("Malgun Gothic", 13, "normal"))
            self.assertEqual(font_support.ui_font(SimpleNamespace(), 20, "timer"), ("Malgun Gothic", 20, "bold"))

    def test_single_family_tk_enumeration_still_has_weight(self):
        with patch.object(font_support.tkfont, "families", return_value=("Pretendard",)):
            self.assertEqual(font_support.ui_font(SimpleNamespace(), 20, "timer"), ("Pretendard", 20, "bold"))

    def test_windows_registration_is_private_and_idempotent(self):
        calls = []

        class AddFont:
            def __call__(self, path, flags, reserved):
                calls.append((path, flags, reserved))
                return 1

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in font_support.FONT_FILES:
                (root / name).write_bytes(b"test font registration")
            with patch.object(font_support, "bundled_font_directory", return_value=root), \
                 patch.object(font_support, "_registered_paths", set()), \
                 patch.object(font_support.os, "name", "nt"), \
                 patch.object(font_support.ctypes, "WinDLL", create=True,
                              return_value=SimpleNamespace(AddFontResourceExW=AddFont())):
                self.assertEqual(font_support.register_bundled_fonts(), 4)
                self.assertEqual(font_support.register_bundled_fonts(), 0)
            self.assertEqual(len(calls), 4)
            self.assertTrue(all(flags == 0x10 and reserved is None for _, flags, reserved in calls))

    def test_packaged_assets_are_resolved_from_pyinstaller_root(self):
        with patch.object(font_support.sys, "_MEIPASS", "/tmp/kyunghee-bundle", create=True):
            self.assertEqual(font_support.bundled_font_directory(), Path("/tmp/kyunghee-bundle/assets/fonts"))

    def test_distributed_korean_faces_keep_their_license(self):
        directory = Path(font_support.__file__).resolve().parent / "assets" / "fonts"
        for name in font_support.FONT_FILES:
            with self.subTest(name=name):
                self.assertTrue((directory / name).is_file())
                self.assertGreater((directory / name).stat().st_size, 100_000)
        self.assertIn("SIL OPEN FONT LICENSE", (directory / "LICENSE").read_text())


if __name__ == "__main__":
    unittest.main()
