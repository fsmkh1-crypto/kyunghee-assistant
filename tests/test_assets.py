import unittest
from PIL import Image
from asset_manager import resolve_asset


class AssetTests(unittest.TestCase):
    def test_all_runtime_roles_resolve_and_open(self):
        for role in ("default", "playful", "cheer", "cute_cheer", "nag", "worry", "praise", "master_face"):
            with self.subTest(role=role):
                path = resolve_asset(role)
                self.assertIsNotNone(path, role)
                self.assertTrue(path.is_file(), path)
                with Image.open(path) as image:
                    image.verify()


if __name__ == "__main__":
    unittest.main()
