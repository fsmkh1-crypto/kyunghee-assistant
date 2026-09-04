import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

import import_asset_sheet as tool


class ImportAssetSheetTests(unittest.TestCase):
    def test_refine_alpha_unpremultiplies_black_matted_edge(self):
        rgb = np.zeros((7, 7, 3), dtype=np.uint8)
        mask = np.zeros((7, 7), dtype=bool)
        mask[1:6, 1:6] = True
        rgb[2:5, 2:5] = (180, 120, 90)
        rgb[1, 1:6] = (12, 8, 6)
        rgb[5, 1:6] = (12, 8, 6)
        rgb[1:6, 1] = (12, 8, 6)
        rgb[1:6, 5] = (12, 8, 6)
        straight, alpha, core = tool.refine_alpha(rgb, mask, edge_low=2, edge_high=28)
        self.assertTrue(core[3, 3])
        self.assertGreater(alpha[1, 3], 0)
        self.assertLess(alpha[1, 3], 255)
        self.assertGreater(int(straight[1, 3].max()), int(rgb[1, 3].max()))

    def test_different_clothing_colour_is_not_near_duplicate(self):
        alpha = np.zeros((64, 64), dtype=np.uint8)
        alpha[8:56, 16:48] = 255
        red = np.zeros((64, 64, 3), dtype=np.uint8)
        purple = np.zeros_like(red)
        red[alpha > 0] = (210, 55, 45)
        purple[alpha > 0] = (120, 55, 190)
        red_sig = tool.signatures(red, alpha)
        purple_sig = tool.signatures(purple, alpha)
        index = {
            "schema_version": 1,
            "sources": {},
            "assets": {
                "assets/cheer/cheer_01.png": {
                    "role": "cheer",
                    "sha256": "old",
                    **red_sig,
                }
            },
        }
        record = {
            "role": "cheer",
            "file": "cheer_02.png",
            "sha256": "new",
            "signature": purple_sig,
        }
        warnings = tool.annotate_duplicates(index, [record])
        self.assertEqual(warnings, [])

    def test_same_appearance_with_different_bytes_is_near_duplicate(self):
        alpha = np.zeros((64, 64), dtype=np.uint8)
        alpha[8:56, 16:48] = 255
        rgb = np.zeros((64, 64, 3), dtype=np.uint8)
        rgb[alpha > 0] = (180, 80, 90)
        sig = tool.signatures(rgb, alpha)
        index = {
            "schema_version": 1,
            "sources": {},
            "assets": {
                "assets/default/default_01.png": {
                    "role": "default",
                    "sha256": "old",
                    **sig,
                }
            },
        }
        record = {
            "role": "default",
            "file": "default_02.png",
            "sha256": "new",
            "signature": sig,
        }
        warnings = tool.annotate_duplicates(index, [record])
        self.assertEqual(len(warnings), 1)
        self.assertEqual(warnings[0]["kind"], "near")

    def test_existing_unmanaged_preview_directory_is_never_deleted(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            repo = root / "repo"
            repo.mkdir()
            victim = root / "documents"
            victim.mkdir()
            keep = victim / "keep.txt"
            keep.write_text("keep", encoding="utf-8")
            with self.assertRaises(SystemExit):
                tool.prepare_preview_dir(repo, victim)
            self.assertEqual(keep.read_text(encoding="utf-8"), "keep")

    def test_synthetic_standard_sheet_splits_to_ten_roles(self):
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            source = td / "sheet.png"
            image = Image.new("RGB", (1000, 600), (0, 0, 0))
            draw = ImageDraw.Draw(image)
            for row in range(2):
                for col in range(5):
                    cx = col * 200 + 100
                    cy = row * 300 + 150
                    draw.ellipse((cx - 55, cy - 100, cx + 55, cy + 100), fill=(190, 130, 110))
            image.save(source)
            output = td / "out"
            records, diagnostics = tool.split_sheet(
                source,
                output,
                7,
                {role: [] for role in tool.ROLES},
                bg_threshold=4,
                margin_fraction=0.05,
                peaks_per_cell=1,
                cell_inset=0.05,
                min_component_area=20,
                edge_low=2,
                edge_high=28,
                centroid_tolerance=0.8,
            )
            self.assertEqual([record["role"] for record in records], list(tool.ROLES))
            self.assertEqual(len(list(output.glob("*_07.png"))), 10)
            self.assertIn("row_split", diagnostics)


if __name__ == "__main__":
    unittest.main()
