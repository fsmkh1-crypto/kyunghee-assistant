import tempfile
import unittest
from pathlib import Path
import sys

import numpy as np
from PIL import Image

TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import asset_display_lab as lab


class AssetDisplayLabTests(unittest.TestCase):
    def test_measure_mask_counts_edges_and_components(self):
        mask = np.zeros((6, 6), dtype=bool)
        mask[1:5, 1:5] = True
        metric = lab.measure_mask(mask)
        self.assertEqual(metric.area, 16)
        self.assertGreater(metric.transitions, 0)
        self.assertEqual(metric.large_components, 0)

    def test_compare_identical_mask_is_zero(self):
        mask = np.zeros((8, 8), dtype=bool)
        mask[2:6, 2:6] = True
        metric = lab.measure_mask(mask)
        result = lab.compare_mask(mask, mask.copy(), metric, metric)
        self.assertEqual(result[:4], (0.0, 0.0, 0.0, 0.0))
        self.assertFalse(result[4])

    def test_discover_assets_requires_complete_numbered_set(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for role in lab.ROLES:
                folder = root / role
                folder.mkdir(parents=True, exist_ok=True)
                Image.new("RGBA", (8, 8), (255, 255, 255, 255)).save(folder / f"{role}_01.png")
            found = lab.discover_assets(root)
            self.assertEqual(len(found), len(lab.ROLES))

            (root / "alert" / "alert_01.png").unlink()
            with self.assertRaises(SystemExit):
                lab.discover_assets(root)

    def test_smoothing_variant_stays_binary(self):
        image = Image.new("RGBA", (7, 7), (255, 255, 255, 0))
        alpha = image.getchannel("A")
        for y in range(1, 6):
            alpha.putpixel((3, y), 255)
        image.putalpha(alpha)
        mask = lab.colorkey_mask(image, lab.Variant(112, 0.35))
        self.assertEqual(mask.dtype, np.bool_)
        self.assertTrue(mask.any())


if __name__ == "__main__":
    unittest.main()
