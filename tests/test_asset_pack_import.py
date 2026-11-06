import hashlib
import io
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image
from asset_pack_import import import_numbered_pack, ROLES


def png(color="pink"):
    output = io.BytesIO()
    Image.new("RGBA", (8, 12), color).save(output, "PNG")
    return output.getvalue()


class AdditivePackTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.assets = self.base / "assets"
        self.archive = self.base / "original.zip"

    def pack(self, roles=ROLES, color="pink", extras=None):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for role in roles:
                archive.writestr(f"package/assets/{role}/{role}_22.png", png(color))
            for path, data in (extras or {}).items():
                archive.writestr(path, data)

    def test_complete_pack_adds_only_numbered_pngs_and_preserves_source_masters_and_duplicates(self):
        self.pack(extras={"main_kyunghee.png": png(), "app.exe": b"ignored", "settings.json": b"ignored"})
        before = hashlib.sha256(self.archive.read_bytes()).digest()
        master = self.assets / "default" / "main_kyunghee.png"
        master.parent.mkdir(parents=True)
        master.write_bytes(b"preserve-master")
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result.added, 10)
        self.assertEqual(result.sets, ("22",))
        self.assertEqual(master.read_bytes(), b"preserve-master")
        self.assertEqual(hashlib.sha256(self.archive.read_bytes()).digest(), before)
        self.assertEqual(len(list(self.assets.rglob("*.png"))), 11)
        self.assertFalse((self.assets / "app.exe").exists())
        repeated = import_numbered_pack(self.archive, self.assets)
        self.assertEqual((repeated.added, repeated.identical), (0, 10))

    def test_conflict_aborts_before_any_write(self):
        self.pack()
        installed = self.assets / "warning" / "warning_22.png"
        installed.parent.mkdir(parents=True)
        installed.write_bytes(b"existing-asset")
        with self.assertRaises(ValueError):
            import_numbered_pack(self.archive, self.assets)
        self.assertEqual(installed.read_bytes(), b"existing-asset")
        self.assertEqual(list(self.assets.rglob("*.png")), [installed])

    def test_incomplete_or_invalid_pack_never_creates_destination(self):
        self.pack(roles=ROLES - {"profile"})
        with self.assertRaises(ValueError):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())
        self.pack(extras={"other/profile_22.png": b"invalid PNG"})
        with self.assertRaises(ValueError):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_zip_paths_cannot_escape_numbered_role_destinations(self):
        self.pack(extras={"../../outside.txt": b"ignored", "../../ignored.py": b"ignored"})
        import_numbered_pack(self.archive, self.assets)
        self.assertFalse((self.base / "outside.txt").exists())
        self.assertEqual(len(list(self.assets.rglob("*.png"))), 10)

    def test_differing_duplicate_zip_entry_and_link_destinations_are_rejected(self):
        self.pack(extras={"other/default_22.png": png("blue")})
        with self.assertRaises(ValueError):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())
        self.pack()
        self.assets.mkdir()
        outside = self.base / "outside"
        outside.mkdir()
        try:
            (self.assets / "default").symlink_to(outside, target_is_directory=True)
        except OSError:
            self.skipTest("The current account cannot create directory symbolic links")
        with self.assertRaises(ValueError):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(list(outside.iterdir()))


if __name__ == "__main__":
    unittest.main()
