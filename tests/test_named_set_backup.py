"""Named collections must survive portable backups with their selection intact."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from named_image_sets import NamedImageSetStore, ROLES
from settings import UserSettings, load_user_settings
import user_data_backup as backup


class NamedSetBackupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.archive = self.root / "named.seunga-backup.zip"
        self.sources = self.root / "sources"
        self.sources.mkdir()
        self.assignments = {}
        for index, role in enumerate(ROLES):
            path = self.sources / (role + ".png")
            Image.new("RGBA", (8, 12), (index * 20, 40, 70, 255)).save(path)
            self.assignments[role] = path
        self.store = NamedImageSetStore(self.profile / "image_sets")

    def create_set(self, name="승아의 봄"):
        item = self.store.save(self.store.preview(name, self.assignments))
        (self.profile / "settings.json").write_text(json.dumps(asdict(
            UserSettings(builtin_image_set=item.id, break_interval_minutes=45))), encoding="utf-8")
        (self.profile / "manual_asset_overrides.json").write_text(
            json.dumps({"__base_set__": item.id, "away": "__follow_selected_set__"}), encoding="utf-8")
        return item

    def rewrite(self, mutate):
        with zipfile.ZipFile(self.archive) as source:
            files = {name: source.read(name) for name in source.namelist()}
        manifest = json.loads(files["manifest.json"])
        mutate(files, manifest)
        for entry in manifest["files"]:
            data = files["data/" + entry["name"]]
            entry.update(size=len(data), sha256=hashlib.sha256(data).hexdigest())
        files["manifest.json"] = json.dumps(manifest).encode()
        with zipfile.ZipFile(self.archive, "w") as target:
            for name, data in files.items():
                target.writestr(name, data)

    def test_round_trip_preserves_named_selection_old_role_images_and_zip_images(self):
        item = self.create_set()
        old_image = self.profile / "image_sets/roles/default/old.png"
        old_image.parent.mkdir(parents=True)
        old_image.write_bytes(self.assignments["default"].read_bytes())
        (self.profile / "image_sets/image_sets.json").write_text(json.dumps({
            "schema_version": 1, "roles": {"default": {"images": ["roles/default/old.png"]}}}))
        old_zip = self.profile / "imported_assets/default/default_22.png"
        old_zip.parent.mkdir(parents=True)
        old_zip.write_bytes(self.assignments["rest"].read_bytes())
        backup.create_backup(self.profile, self.archive, ("settings", "images"))
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertFalse(any(name.endswith(".lock") for name in bundle.namelist()))
            self.assertIn(f"data/image_sets/named/{item.id[6:]}/manifest.json", bundle.namelist())
        destination = self.root / "moved-profile"
        backup.restore_backup(self.archive, destination, ("settings", "images"), app_is_quiescent=True)
        restored = NamedImageSetStore(destination / "image_sets")
        self.assertEqual(restored.get(item.id).name, item.name)
        for role in ROLES:
            self.assertEqual(restored.resolve(item.id, role).read_bytes(), self.assignments[role].read_bytes())
        self.assertEqual(load_user_settings(destination / "settings.json").builtin_image_set, item.id)
        self.assertEqual(load_user_settings(destination / "settings.json").break_interval_minutes, 45)
        self.assertEqual(json.loads((destination / "manual_asset_overrides.json").read_text())["__base_set__"], item.id)
        self.assertEqual((destination / old_image.relative_to(self.profile)).read_bytes(), old_image.read_bytes())
        self.assertEqual((destination / old_zip.relative_to(self.profile)).read_bytes(), old_zip.read_bytes())

    def test_unpublished_partial_set_is_excluded_from_backup(self):
        item = self.create_set()
        partial = self.profile / "image_sets/named" / ("b" * 32)
        partial.mkdir()
        (partial / "default.png").write_bytes(self.assignments["default"].read_bytes())
        backup.create_backup(self.profile, self.archive, ("images",))
        with zipfile.ZipFile(self.archive) as bundle:
            self.assertFalse(any("b" * 32 in name for name in bundle.namelist()))
            self.assertIn(f"data/image_sets/named/{item.id[6:]}/manifest.json", bundle.namelist())
        self.assertTrue((partial / "default.png").exists())

    def test_redacted_name_keeps_valid_id_and_per_role_reference(self):
        secret = "sk-notarealkey123456789"
        item = self.create_set("내 그림 " + secret)
        reference = "userset:named/" + item.id[6:] + "/rest.png"
        (self.profile / "manual_asset_overrides.json").write_text(json.dumps({
            "__base_set__": item.id, "default": reference}), encoding="utf-8")
        backup.create_backup(self.profile, self.archive, ("settings", "images"))
        with zipfile.ZipFile(self.archive) as bundle:
            for name in bundle.namelist():
                if name.endswith(".json"):
                    self.assertNotIn(secret.encode(), bundle.read(name))
        destination = self.root / "redacted-profile"
        backup.restore_backup(self.archive, destination, ("settings", "images"), app_is_quiescent=True)
        restored = NamedImageSetStore(destination / "image_sets").get(item.id)
        self.assertIsNotNone(restored)
        self.assertNotEqual(restored.name, item.name)
        self.assertIn(item.id[6:], restored.name)
        self.assertEqual(json.loads((destination / "manual_asset_overrides.json").read_text()),
                         {"__base_set__": item.id, "default": reference})
        self.assertEqual(self.store.get(item.id).name, item.name)

    def test_missing_changed_or_escaping_set_image_rejects_restore_before_replacement(self):
        item = self.create_set()
        backup.create_backup(self.profile, self.archive, ("images",))
        original = self.archive.read_bytes()
        destination = self.root / "destination"
        destination.mkdir()
        original_file = destination / "keep.txt"
        original_file.write_bytes(b"existing-profile")
        image_name = f"image_sets/named/{item.id[6:]}/default.png"
        description = f"data/image_sets/named/{item.id[6:]}/manifest.json"
        for kind in ("missing", "changed", "escaping", "wrong-id"):
            with self.subTest(kind=kind):
                self.archive.write_bytes(original)
                def corrupt(files, manifest):
                    if kind == "missing":
                        del files["data/" + image_name]
                        manifest["files"] = [e for e in manifest["files"] if e["name"] != image_name]
                    elif kind == "changed":
                        files["data/" + image_name] = self.assignments["rest"].read_bytes()
                    else:
                        raw = json.loads(files[description])
                        if kind == "escaping":
                            raw["images"]["default"]["file"] = "../outside.png"
                        else:
                            raw["id"] = "named:" + "c" * 32
                        files[description] = json.dumps(raw).encode()
                self.rewrite(corrupt)
                with self.assertRaises(backup.BackupError):
                    backup.restore_backup(self.archive, destination, ("images",), app_is_quiescent=True)
                self.assertEqual(original_file.read_bytes(), b"existing-profile")
                self.assertEqual(list(destination.iterdir()), [original_file])

    def test_corrupt_live_collection_preserves_an_existing_backup(self):
        item = self.create_set()
        backup.create_backup(self.profile, self.archive, ("images",))
        original = self.archive.read_bytes()
        self.store.resolve(item.id, "default").unlink()
        with self.assertRaises(backup.BackupError):
            backup.create_backup(self.profile, self.archive, ("images",))
        self.assertEqual(self.archive.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
