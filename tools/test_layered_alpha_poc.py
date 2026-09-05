from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

from PIL import Image


MODULE_PATH = Path(__file__).with_name("layered_alpha_poc.py")
spec = importlib.util.spec_from_file_location("layered_alpha_poc", MODULE_PATH)
poc = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(poc)


class LayeredAlphaPocTests(unittest.TestCase):
    def test_premultiplied_bgra_channel_order_and_alpha(self):
        image = Image.new("RGBA", (3, 1))
        image.putdata([
            (100, 50, 200, 255),
            (100, 50, 200, 128),
            (100, 50, 200, 0),
        ])
        raw = poc.premultiplied_bgra_bytes(image)
        pixels = [tuple(raw[i:i + 4]) for i in range(0, len(raw), 4)]
        self.assertEqual(pixels[0], (200, 50, 100, 255))
        self.assertEqual(pixels[1], (100, 25, 50, 128))
        self.assertEqual(pixels[2], (0, 0, 0, 0))

    def test_prepare_image_preserves_soft_alpha(self):
        image = Image.new("RGBA", (8, 8), (10, 20, 30, 0))
        image.putpixel((4, 4), (100, 110, 120, 128))
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.png"
            image.save(path)
            prepared = poc.prepare_image(path, (8, 8))
        self.assertEqual(prepared.mode, "RGBA")
        self.assertEqual(prepared.getpixel((4, 4))[3], 128)

    def test_default_asset_is_review_priority_candidate(self):
        self.assertEqual(poc.DEFAULT_ASSET.as_posix(), "assets/away/away_02.png")


if __name__ == "__main__":
    unittest.main()
