#!/usr/bin/env python3
"""Apply the reviewed conservative built-in edge-smoothing runtime patch."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected patch anchor not found in {path}: {old[:80]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"Patch anchor is not unique in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


image_render = ROOT / "image_render.py"
replace_once(
    image_render,
    "from PIL import Image, ImageOps\n",
    "from PIL import Image, ImageFilter, ImageOps\n",
)
replace_once(
    image_render,
    '''def threshold_alpha(image: Image.Image, threshold: int = DEFAULT_ALPHA_THRESHOLD) -> Image.Image:\n    """Convert alpha to binary transparency for Tk color-key windows after resizing."""\n    if not 0 <= threshold <= 255:\n        raise ValueError("alpha threshold must be between 0 and 255")\n    rgba = image.convert("RGBA")\n    alpha = rgba.getchannel("A")\n    rgba.putalpha(alpha.point(lambda value: 0 if value < threshold else 255))\n    return rgba\n''',
    '''def threshold_alpha(\n    image: Image.Image,\n    threshold: int = DEFAULT_ALPHA_THRESHOLD,\n    *,\n    smooth_radius: float = 0.0,\n) -> Image.Image:\n    """Convert alpha to binary transparency for Tk color-key windows after resizing.\n\n    ``smooth_radius`` gently regularizes the resized alpha mask before the binary\n    color-key cut.  A zero radius preserves the historical behavior exactly.\n    """\n    if not 0 <= threshold <= 255:\n        raise ValueError("alpha threshold must be between 0 and 255")\n    if smooth_radius < 0:\n        raise ValueError("alpha smooth radius must be non-negative")\n    rgba = image.convert("RGBA")\n    alpha = rgba.getchannel("A")\n    if smooth_radius:\n        alpha = alpha.filter(ImageFilter.GaussianBlur(radius=float(smooth_radius)))\n    rgba.putalpha(alpha.point(lambda value: 0 if value < threshold else 255))\n    return rgba\n''',
)

compact = ROOT / "desktop_compact.py"
replace_once(
    compact,
    "MAX_CUSTOM_IMAGE_DIMENSION = 4000\n",
    "MAX_CUSTOM_IMAGE_DIMENSION = 4000\nBUILTIN_ALPHA_SMOOTH_RADIUS = 0.35\n",
)
replace_once(
    compact,
    '''    @staticmethod\n    def _clean_character_alpha(image):\n        return threshold_alpha(image)\n''',
    '''    @staticmethod\n    def _clean_character_alpha(image, *, smooth_radius=0.0):\n        return threshold_alpha(image, smooth_radius=smooth_radius)\n''',
)
replace_once(
    compact,
    '''        self._image_set_choices.pop(role, None)\n        try:\n            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))\n            image = self._load_character_image(role, max_size, preserve_alpha=True)\n            image = self._clean_character_alpha(image)\n''',
    '''        self._image_set_choices.pop(role, None)\n        try:\n            # Establish any user-selected image before loading so built-in-only\n            # mask smoothing never changes user supplied artwork.  _custom_image\n            # stores an image-set choice, so _load_character_image reuses it.\n            custom, _mode, _centering = self._custom_image(role)\n            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))\n            image = self._load_character_image(role, max_size, preserve_alpha=True)\n            smooth_radius = 0.0 if custom is not None else BUILTIN_ALPHA_SMOOTH_RADIUS\n            image = self._clean_character_alpha(image, smooth_radius=smooth_radius)\n''',
)

tests = ROOT / "tests" / "test_image_render.py"
replace_once(
    tests,
    '''    def test_threshold_rejects_invalid_value(self):\n        with self.assertRaises(ValueError):\n            threshold_alpha(Image.new("RGBA", (1, 1)), 300)\n''',
    '''    def test_threshold_rejects_invalid_value(self):\n        with self.assertRaises(ValueError):\n            threshold_alpha(Image.new("RGBA", (1, 1)), 300)\n\n    def test_threshold_optional_smoothing_stays_binary(self):\n        source = Image.new("RGBA", (7, 7), (255, 0, 0, 0))\n        alpha = source.getchannel("A")\n        for y in range(1, 6):\n            alpha.putpixel((3, y), 255)\n        source.putalpha(alpha)\n        result = threshold_alpha(source, 112, smooth_radius=0.35)\n        self.assertTrue(set(result.getchannel("A").getdata()).issubset({0, 255}))\n\n    def test_threshold_rejects_negative_smoothing(self):\n        with self.assertRaises(ValueError):\n            threshold_alpha(Image.new("RGBA", (1, 1)), smooth_radius=-0.1)\n''',
)

print("Applied conservative built-in alpha mask smoothing patch")
