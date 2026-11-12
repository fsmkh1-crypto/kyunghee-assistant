from pathlib import Path
import tempfile
import unittest
from PIL import Image
from image_catalog import ImageCatalog, valid_image


class ImageCatalogTests(unittest.TestCase):
    def test_catalog_decodes_images_and_rejects_escape_or_unowned_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'assets'
            (root / 'default').mkdir(parents=True)
            good = root / 'default' / 'default_01.png'
            Image.new('RGBA', (12, 20), 'pink').save(good)
            bad = root / 'default' / 'corrupt.png'
            bad.write_bytes(good.read_bytes()[:50])
            outside = base / 'outside.png'
            Image.new('RGBA', (12, 20), 'blue').save(outside)
            catalog = ImageCatalog({'builtin': root}, {'default': '평상시'})
            self.assertEqual([item.ref for item in catalog.entries()], ['builtin:default/default_01.png'])
            self.assertIsNone(catalog.decode('builtin:../outside.png'))
            self.assertIsNone(catalog.decode('absolute:' + str(outside)))
            with self.assertRaises(ValueError):
                catalog.encode(outside)
            self.assertFalse(valid_image(bad))

    def test_committed_corrupt_master_is_excluded_without_modifying_artwork(self):
        path = Path(__file__).resolve().parents[1] / 'assets/profile/master_face.png'
        before = path.read_bytes()
        self.assertFalse(valid_image(path))
        self.assertEqual(path.read_bytes(), before)
