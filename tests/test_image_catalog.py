from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
from image_catalog import ImageCatalog, valid_image


class ImageCatalogTests(unittest.TestCase):
    @staticmethod
    def image(path, color='pink'):
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGBA', (12, 20), color).save(path)
        return path

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

    def test_named_sets_preserve_legacy_image_roots_and_public_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            roots = {origin: base / origin for origin in ('builtin', 'imported', 'user', 'userset')}
            paths = {
                'builtin:default/default_01.png': self.image(roots['builtin'] / 'default/default_01.png'),
                'imported:default/default_01.png': self.image(roots['imported'] / 'default/default_01.png', 'blue'),
                'user:rest_legacy.png': self.image(roots['user'] / 'rest_legacy.png'),
                'userset:roles/rest/legacy.png': self.image(roots['userset'] / 'roles/rest/legacy.png'),
            }
            before = {path: path.read_bytes() for path in paths.values()}
            catalog = ImageCatalog(roots, {'default': '평상시', 'rest': '휴식'})
            entries = catalog.entries()
            self.assertEqual({item.ref for item in entries}, set(paths))
            for item in entries:
                self.assertIsNone(item.set_id)
                self.assertEqual(set(item.public()), {'ref', 'role', 'label', 'origin', 'version'})
                self.assertEqual(catalog.decode(item.ref), paths[item.ref])
            self.assertEqual({path: path.read_bytes() for path in paths.values()}, before)
            self.assertFalse((roots['userset'] / 'named').exists())

    def test_named_complete_sets_keep_unique_identity_and_all_ten_assignments(self):
        from named_image_sets import NamedImageSetStore, ROLES
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'usersets'
            source = self.image(base / 'source' / 'arbitrary_portrait_01.png')
            source_before = source.read_bytes()
            assignments = {role: source for role in ROLES}
            store = NamedImageSetStore(root)
            first = store.create('주말 01', assignments)
            second = store.create('주말 01', assignments)
            legacy = self.image(root / 'roles' / 'rest' / 'older.png')
            catalog = ImageCatalog({'userset': root}, {role: role for role in ROLES})

            entries = catalog.entries()
            self.assertEqual(len(entries), 21)
            self.assertNotEqual(first.id, second.id)
            self.assertNotEqual(first.name, second.name)
            for image_set in (first, second):
                members = [item for item in entries if item.set_id == image_set.id]
                self.assertEqual({item.role for item in members}, set(ROLES))
                self.assertEqual(len(members), 10)
                for item in members:
                    self.assertEqual(item.origin, 'userset')
                    self.assertEqual(item.path, image_set.images[item.role])
                    self.assertEqual(item.ref, 'userset:' + item.path.relative_to(root).as_posix())
                    self.assertEqual(catalog.decode(item.ref), item.path)
                    self.assertEqual(item.public()['set_id'], image_set.id)
                    self.assertEqual(item.label, f'{image_set.name} · {item.path.name}')
            self.assertEqual([item.path for item in entries if item.set_id is None], [legacy])
            self.assertEqual(source.read_bytes(), source_before)

    def test_named_catalog_excludes_orphan_partial_and_corrupt_sets_without_repairing(self):
        from named_image_sets import NamedImageSetStore, ROLES
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'usersets'
            source = self.image(base / 'source.png')
            store = NamedImageSetStore(root)
            assignments = {role: source for role in ROLES}
            complete, damaged, partial, broken = [store.create(name, assignments)
                                                  for name in ('완전', '손상', '일부', '기록 손상')]
            damaged.images['rest'].write_bytes(b'broken image')
            partial.images['profile'].unlink()
            broken_manifest = broken.images['default'].parent / 'manifest.json'
            broken_manifest.write_bytes(b'{broken manifest')
            self.image(root / 'named' / ('f' * 32) / 'default.png')
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob('*') if path.is_file()}

            entries = ImageCatalog({'userset': root}, {role: role for role in ROLES}).entries()
            self.assertEqual(len(entries), 10)
            self.assertEqual({item.set_id for item in entries}, {complete.id})
            self.assertEqual({path.relative_to(root): path.read_bytes()
                              for path in root.rglob('*') if path.is_file()}, before)

    def test_image_disappearing_after_named_validation_does_not_publish_partial_set(self):
        from named_image_sets import NamedImageSetStore, ROLES
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            source = self.image(base / 'source.png')
            root = base / 'usersets'
            image_set = NamedImageSetStore(root).create('이동 중', {role: source for role in ROLES})
            catalog = ImageCatalog({'userset': root}, {role: role for role in ROLES})
            encode = catalog.encode
            def remove_during_encoding(path):
                if path == image_set.images['rest']:
                    path.unlink()
                return encode(path)
            with patch.object(catalog, 'encode', side_effect=remove_during_encoding):
                self.assertEqual(catalog.entries(), [])
