import unittest

from PIL import Image

from image_render import resize_rgba_alpha_safe, threshold_alpha


class ImageRenderTests(unittest.TestCase):
    def test_contain_preserves_aspect_ratio(self):
        source = Image.new("RGBA", (1200, 900), (255, 0, 0, 255))
        resized = resize_rgba_alpha_safe(source, (300, 300))
        self.assertEqual(resized.size, (300, 225))

    def test_crop_matches_requested_size(self):
        source = Image.new("RGBA", (600, 900), (255, 0, 0, 255))
        resized = resize_rgba_alpha_safe(source, (300, 300), crop=True)
        self.assertEqual(resized.size, (300, 300))

    def test_threshold_alpha_binary_output(self):
        source = Image.new("RGBA", (2, 1))
        source.putdata([(255, 0, 0, 50), (255, 0, 0, 200)])
        result = threshold_alpha(source, 112)
        self.assertEqual(list(result.getchannel("A").getdata()), [0, 255])

    def test_threshold_rejects_invalid_value(self):
        with self.assertRaises(ValueError):
            threshold_alpha(Image.new("RGBA", (1, 1)), 300)


if __name__ == "__main__":
    unittest.main()
