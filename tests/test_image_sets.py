from pathlib import Path
import random
import tempfile
import unittest

from image_sets import ImageSetStore, normalize_alignment, normalize_fit_mode


class ImageSetStoreTests(unittest.TestCase):
    def _write_image_stub(self, path: Path, content: bytes = b"stub") -> Path:
        path.write_bytes(content)
        return path

    def test_import_files_copies_into_app_owned_role_folder(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_dir = base / "source"
            source_dir.mkdir()
            source = self._write_image_stub(source_dir / "one.png")
            store = ImageSetStore(base / "owned")

            config = store.import_files("cheer", [source])
            images = store.list_images("cheer")

            self.assertEqual(len(config.images), 1)
            self.assertEqual(len(images), 1)
            self.assertTrue(images[0].is_file())
            self.assertEqual(images[0].parent.name, "cheer")
            self.assertNotEqual(images[0], source)

    def test_import_folder_ignores_unsupported_files(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_dir = base / "source"
            source_dir.mkdir()
            self._write_image_stub(source_dir / "a.png")
            self._write_image_stub(source_dir / "b.webp")
            self._write_image_stub(source_dir / "ignore.txt")
            store = ImageSetStore(base / "owned")

            store.import_folder("rest", source_dir)
            names = {path.suffix.lower() for path in store.list_images("rest")}

            self.assertEqual(names, {".png", ".webp"})

    def test_choose_uses_random_selection_from_registered_set(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_dir = base / "source"
            source_dir.mkdir()
            paths = [self._write_image_stub(source_dir / f"{index}.png", bytes([index])) for index in range(3)]
            store = ImageSetStore(base / "owned")
            store.import_files("default", paths)

            rng = random.Random(7)
            selected = {store.choose("default", rng).name for _ in range(20)}

            self.assertGreaterEqual(len(selected), 2)

    def test_missing_imported_file_is_skipped_without_breaking_set(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source_dir = base / "source"
            source_dir.mkdir()
            paths = [self._write_image_stub(source_dir / "a.png"), self._write_image_stub(source_dir / "b.png")]
            store = ImageSetStore(base / "owned")
            store.import_files("away", paths)
            imported = store.list_images("away")
            imported[0].unlink()

            remaining = store.list_images("away")

            self.assertEqual(len(remaining), 1)
            self.assertTrue(remaining[0].is_file())

    def test_fit_and_alignment_options_are_normalized(self):
        with tempfile.TemporaryDirectory() as directory:
            store = ImageSetStore(Path(directory) / "owned")
            updated = store.set_options("warning", fit_mode="crop", alignment="top_right")
            self.assertEqual(updated.fit_mode, "crop")
            self.assertEqual(updated.alignment, "top_right")

            updated = store.set_options("warning", fit_mode="bad", alignment="bad")
            self.assertEqual(updated.fit_mode, "fit")
            self.assertEqual(updated.alignment, "center")

        self.assertEqual(normalize_fit_mode("bad"), "fit")
        self.assertEqual(normalize_alignment("bad"), "center")

    def test_clear_removes_role_files_but_keeps_options(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = self._write_image_stub(base / "a.png")
            store = ImageSetStore(base / "owned")
            store.set_options("leave", fit_mode="crop", alignment="bottom")
            store.import_files("leave", [source])

            cleared = store.clear("leave")

            self.assertEqual(cleared.images, ())
            self.assertEqual(cleared.fit_mode, "crop")
            self.assertEqual(cleared.alignment, "bottom")
            self.assertEqual(store.list_images("leave"), ())


if __name__ == "__main__":
    unittest.main()
