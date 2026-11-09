"""Importer checks use tiny synthetic PNG fixtures, never user artwork."""

import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from PIL import Image
import asset_pack_import
from asset_pack_import import CANONICAL_ALIASES, ImportResult, import_numbered_pack, ROLES


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

    def write_entries(self, entries):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for path, data in entries.items():
                archive.writestr(path, data)

    def role_entries(self, prefix="pack", roles=ROLES, color="pink", style="role"):
        result = {}
        aliases = {role: name for name, role in CANONICAL_ALIASES.items()}
        for role in roles:
            name = {"role": f"{role}.png", "folder": f"{role}/Image.png",
                    "alias": aliases[role]}[style]
            result[f"{prefix}/{name}"] = png(color)
        return result

    def install_fixture(self, number, roles=ROLES, color="pink"):
        for role in roles:
            target = self.assets / role / f"{role}_{number}.png"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(png(color))

    def snapshot(self):
        return {path.relative_to(self.assets).as_posix(): path.read_bytes()
                for path in self.assets.rglob("*") if path.is_file()}

    def make_link(self, link, target, directory=False):
        try:
            link.symlink_to(target, target_is_directory=directory)
        except OSError:
            self.skipTest("The current account cannot create symbolic links")

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

    def test_result_keeps_three_argument_compatibility(self):
        result = ImportResult(("22",), 10, 0)
        self.assertEqual((result.auto_assigned, result.reused), ((), ()))

    def test_role_only_pack_assigns_number_and_reimport_reuses_without_writes(self):
        self.write_entries(self.role_entries())
        original = self.archive.read_bytes()
        master = self.assets / "default" / "main_kyunghee.png"
        master.parent.mkdir(parents=True)
        master.write_bytes(b"preserved-master")
        first = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(first, ImportResult(("01",), 10, 0, ("01",), ()))
        before = self.snapshot()
        second = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(second, ImportResult(("01",), 0, 10, (), ("01",)))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(master.read_bytes(), b"preserved-master")
        self.assertEqual(self.archive.read_bytes(), original)

    def test_role_only_pack_finds_whole_installed_set_by_all_ten_hashes(self):
        self.install_fixture("07")
        self.write_entries(self.role_entries(prefix="renamed"))
        before = self.snapshot()
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("07",), 0, 10, (), ("07",)))
        self.assertEqual(self.snapshot(), before)
        entries = self.role_entries()
        entries["pack/profile.png"] = png("blue")
        self.write_entries(entries)
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("01",), 10, 0, ("01",), ()))

    def test_auto_number_reserves_partial_installed_and_incoming_explicit_numbers(self):
        self.install_fixture("01", {"default"})
        self.install_fixture("02", {"rest"})
        before = self.snapshot()
        entries = self.role_entries(prefix="unassigned")
        entries.update({f"numbered/{role}_03.png": png("blue") for role in ROLES})
        self.write_entries(entries)
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("03", "04"), 20, 0, ("04",), ()))
        self.assertTrue(before.items() <= self.snapshot().items())

    def test_all_numbers_occupied_fails_without_modifying_partial_sets(self):
        for number in range(1, 100):
            self.install_fixture(f"{number:02}", {"default"})
        before = self.snapshot()
        self.write_entries(self.role_entries())
        with self.assertRaisesRegex(ValueError, "01~99"):
            import_numbered_pack(self.archive, self.assets)
        self.assertEqual(self.snapshot(), before)

    def test_complete_alias_pack_and_role_folder_image_pack_are_supported(self):
        for style in ("alias", "folder"):
            with self.subTest(style=style):
                self.write_entries(self.role_entries(style=style))
                result = import_numbered_pack(self.archive, self.assets)
                expected = ImportResult(("01",), 10, 0, ("01",), ()) if style == "alias" else ImportResult(("01",), 0, 10, (), ("01",))
                self.assertEqual(result, expected)
                self.assertEqual(len(list(self.assets.rglob("*.png"))), 10)
                self.assertFalse(list(self.assets.rglob("*kyunghee.png")))

    def test_numbered_pack_ignores_all_ten_canonical_fallbacks_even_in_another_folder(self):
        for prefix in ("package/assets", "flat"):
            with self.subTest(prefix=prefix):
                # Canonical extras remain ignored, including their byte contents.
                extras = {f"{prefix}/{name}": b"legacy master left untouched"
                          for name in CANONICAL_ALIASES}
                self.pack(extras=extras)
                result = import_numbered_pack(self.archive, self.assets)
                self.assertEqual(result.sets, ("22",))
                self.assertEqual(result.auto_assigned, ())
                self.assertEqual(len(list(self.assets.rglob("*.png"))), 10)

    def test_numbered_pack_ignores_canonical_fallbacks_inside_role_folders(self):
        extras = {f"package/assets/{role}/{name}": b"ignored master"
                  for name, role in CANONICAL_ALIASES.items()}
        self.pack(extras=extras)
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("22",), 10, 0))

    def test_separate_identical_unnumbered_groups_and_incoming_numbered_pack_are_deduplicated(self):
        entries = self.role_entries(prefix="a")
        entries.update(self.role_entries(prefix="b"))
        entries.update({f"explicit/{role}_22.png": png() for role in ROLES})
        self.write_entries(entries)
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("22",), 10, 0, (), ("22",)))
        self.assertEqual(len(list(self.assets.rglob("*.png"))), 10)

    def test_separate_identical_unnumbered_groups_create_one_set(self):
        entries = self.role_entries(prefix="a")
        entries.update(self.role_entries(prefix="b"))
        self.write_entries(entries)
        result = import_numbered_pack(self.archive, self.assets)
        self.assertEqual(result, ImportResult(("01",), 10, 0, ("01",), ()))

    def test_partial_unnumbered_groups_are_not_merged_and_report_missing_roles(self):
        entries = self.role_entries(prefix="a", roles=ROLES - {"profile"})
        entries.update(self.role_entries(prefix="b", roles={"profile"}))
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "profile"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_partial_numbered_set_is_never_completed_from_unnumbered_files(self):
        entries = self.role_entries(prefix="unnumbered")
        entries.update({f"numbered/{role}_22.png": png() for role in ROLES - {"profile"}})
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "세트 22.*profile"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_same_folder_numbered_and_role_only_groups_are_ambiguous(self):
        entries = self.role_entries(prefix="same")
        entries.update({f"same/{role}_22.png": png() for role in ROLES})
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "번호형.*번호 없는"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_conflicting_unnumbered_candidates_abort_and_identical_alias_is_harmless(self):
        entries = self.role_entries()
        entries["pack/main_kyunghee.png"] = png("blue")
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "서로 다른 default"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())
        entries["pack/main_kyunghee.png"] = png()
        self.write_entries(entries)
        self.assertEqual(import_numbered_pack(self.archive, self.assets).added, 10)

    def test_role_filename_conflicting_with_parent_role_is_rejected(self):
        entries = self.role_entries()
        entries["pack/away/cheer.png"] = entries.pop("pack/cheer.png")
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "파일 이름과 역할 폴더"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_unrecognized_zip_explains_supported_names_and_missing_pack_lists_roles(self):
        self.write_entries({"pack/Image.png": png(), "README.txt": b"not a role pack"})
        with self.assertRaises(ValueError) as caught:
            import_numbered_pack(self.archive, self.assets)
        for role in ROLES:
            self.assertIn(f"{role}.png", str(caught.exception))
        self.write_entries(self.role_entries(roles={"default"}))
        with self.assertRaises(ValueError) as caught:
            import_numbered_pack(self.archive, self.assets)
        for role in ROLES - {"default"}:
            self.assertIn(role, str(caught.exception))
        self.assertFalse(self.assets.exists())

    def test_zip_link_member_and_symlinked_destination_root_are_rejected(self):
        info = zipfile.ZipInfo("pack/default.png")
        info.create_system = 3
        info.external_attr = 0o120777 << 16
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, data in self.role_entries(roles=ROLES - {"default"}).items():
                archive.writestr(name, data)
            archive.writestr(info, png())
        with self.assertRaisesRegex(ValueError, "연결된 이미지"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())
        self.write_entries(self.role_entries())
        outside = self.base / "outside"
        outside.mkdir()
        self.make_link(self.assets, outside, directory=True)
        with self.assertRaisesRegex(ValueError, "연결된 에셋 폴더"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(list(outside.iterdir()))

    def test_numbered_target_symlink_cannot_be_overwritten_or_followed(self):
        self.pack()
        outside = self.base / "outside.png"
        outside.write_bytes(b"preserved")
        target = self.assets / "default" / "default_22.png"
        target.parent.mkdir(parents=True)
        self.make_link(target, outside)
        with self.assertRaisesRegex(ValueError, "연결된 에셋 파일"):
            import_numbered_pack(self.archive, self.assets)
        self.assertEqual(outside.read_bytes(), b"preserved")
        self.assertEqual(list(self.assets.rglob("*.png")), [target])

    def test_exclusive_write_collision_rolls_back_only_files_created_by_importer(self):
        self.pack()
        original_zip = self.archive.read_bytes()
        original_open = Path.open
        collision = self.assets / "default" / "default_22.png"

        def racing_open(path, mode="r", *args, **kwargs):
            if path == collision and mode == "xb":
                collision.write_bytes(b"concurrently-created-original")
            return original_open(path, mode, *args, **kwargs)

        with patch.object(Path, "open", new=racing_open):
            with self.assertRaises(FileExistsError):
                import_numbered_pack(self.archive, self.assets)
        self.assertEqual(self.snapshot(), {"default/default_22.png": b"concurrently-created-original"})
        self.assertEqual(self.archive.read_bytes(), original_zip)

    def test_pack_and_image_size_limits_and_invalid_png_fail_before_writes(self):
        self.write_entries(self.role_entries())
        with patch.object(asset_pack_import, "MAX_PACK_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "너무 큽니다"):
                import_numbered_pack(self.archive, self.assets)
        with patch.object(asset_pack_import, "MAX_IMAGE_BYTES", 1):
            with self.assertRaisesRegex(ValueError, "파일 크기"):
                import_numbered_pack(self.archive, self.assets)
        entries = self.role_entries()
        entries["pack/profile.png"] = b"not a PNG fixture"
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, "profile.png.*읽을 수 없습니다"):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_preview_validates_every_image_without_destination_writes(self):
        self.write_entries(self.role_entries())
        result = asset_pack_import.preview_numbered_pack(self.archive, self.assets)
        self.assertEqual(result.added, 10)
        self.assertFalse(self.assets.exists())
        previews = asset_pack_import.preview_role_images(self.archive)
        self.assertEqual(len(previews), 10)
        self.assertTrue(all(image.width <= 76 and image.height <= 88 for _, image in previews))
        self.assertFalse(self.assets.exists())

    def test_recognized_image_traversal_is_rejected_before_any_write(self):
        entries = self.role_entries()
        entries['../../profile.png'] = entries.pop('pack/profile.png')
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, '안전하지'):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())

    def test_legacy_adoption_copies_only_unindexed_sets_and_keeps_originals(self):
        self.install_fixture('01', color='pink')
        self.install_fixture('22', color='blue')
        index = {'assets': {f'assets/{role}/{role}_01.png': {
            'sha256': hashlib.sha256((self.assets / role / f'{role}_01.png').read_bytes()).hexdigest()
        } for role in ROLES}}
        (self.assets / 'asset_index.json').write_text(json.dumps(index), encoding='utf-8')
        profile = self.base / 'profile'
        before = self.snapshot()
        result = asset_pack_import.adopt_legacy_imports(self.assets, profile)
        self.assertEqual(result['copied'], ['22'])
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((profile / 'default/default_01.png').exists())
        self.assertTrue((profile / 'default/default_22.png').exists())
        self.assertEqual(asset_pack_import.adopt_legacy_imports(self.assets, profile), result)
        self.install_fixture('23', color='green')
        new_result = asset_pack_import.adopt_legacy_imports(self.assets, profile)
        self.assertIn('23', new_result['copied'])
        self.assertIn('22', new_result['reused'])

    def test_legacy_adoption_conflict_never_replaces_profile_or_installation(self):
        self.install_fixture('22', color='blue')
        (self.assets / 'asset_index.json').write_text('{"assets": {}}', encoding='utf-8')
        profile = self.base / 'profile'
        (profile / 'default').mkdir(parents=True)
        original = profile / 'default/default_22.png'
        original.write_bytes(png('green'))
        before = self.snapshot()
        result = asset_pack_import.adopt_legacy_imports(self.assets, profile)
        self.assertEqual(result['conflicts'], ['22'])
        self.assertEqual(original.read_bytes(), png('green'))
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(list(profile.rglob('*.png'))), 1)

    def test_partial_numbered_groups_cannot_be_merged_into_a_complete_set(self):
        entries = {f'a/{role}_22.png': png() for role in ROLES - {'profile'}}
        entries['b/profile_22.png'] = png()
        self.write_entries(entries)
        with self.assertRaisesRegex(ValueError, '서로 다른 폴더'):
            import_numbered_pack(self.archive, self.assets)
        self.assertFalse(self.assets.exists())


if __name__ == "__main__":
    unittest.main()
