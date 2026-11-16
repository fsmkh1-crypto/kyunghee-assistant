"""Tiny synthetic fixtures exercise named-set storage without a GUI or network."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from image_sets import ImageSetStore
import named_image_sets as named
from named_image_sets import NamedImageSetStore, ROLES, validate_manifest


class NamedImageSetTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'profile/image_sets'
        self.store = NamedImageSetStore(self.root)
        self.source = self.base / 'originals'
        self.source.mkdir()
        self.assignments = {}
        for index, role in enumerate(ROLES):
            suffix = ('.png', '.jpg', '.webp')[index % 3]
            path = self.source / (role + suffix)
            Image.new('RGB', (9, 12), (index * 20, 75, 150)).save(path)
            self.assignments[role] = path

    def snapshot(self, root=None):
        root = root or self.base
        return {path.relative_to(root).as_posix(): path.read_bytes()
                for path in root.rglob('*') if path.is_file() and path.name != '.named_sets.lock'}

    def manifest(self, image_set):
        return self.store.sets_dir / image_set.id.split(':')[1] / 'manifest.json'

    def link(self, source, target, *, directory=False):
        try:
            target.symlink_to(source, target_is_directory=directory)
        except OSError:
            self.skipTest('The account cannot create symbolic links')

    def test_preview_and_cancel_are_read_only_and_name_is_normalized(self):
        before = self.snapshot()
        plan = self.store.preview('  나의\t새\n세트  ', self.assignments)
        self.assertEqual(plan.name, '나의 새 세트')
        self.assertEqual(plan.sources, self.assignments)
        self.assertFalse(self.root.exists())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.list_sets(), ())

    def test_save_restart_and_every_role_keep_original_bytes_and_other_image_storage(self):
        old = ImageSetStore(self.root)
        old.import_files('rest', [self.assignments['rest']])
        old.set_options('rest', fit_mode='crop', alignment='bottom')
        profile = self.root.parent
        (profile / 'settings.json').write_text('{"builtin_image_set":"pack:22"}', encoding='utf-8')
        (profile / 'manual_asset_overrides.json').write_text('{"default":"imported:default/default_22.png"}', encoding='utf-8')
        numbered = profile / 'imported_assets/default/default_22.png'
        numbered.parent.mkdir(parents=True)
        numbered.write_bytes(self.assignments['default'].read_bytes())
        before = self.snapshot()
        created = self.store.create('집중하는 날', self.assignments)
        self.assertTrue(named.is_named_set_id(created.id))
        self.assertEqual(created.name, '집중하는 날')
        for path, content in before.items():
            self.assertEqual((self.base / path).read_bytes(), content)
        restarted = NamedImageSetStore(self.root)
        self.assertEqual(restarted.list_sets(), (created,))
        for role in ROLES:
            image = restarted.resolve(created.id, role)
            self.assertEqual(image, created.images[role])
            self.assertNotEqual(image, self.assignments[role])
            self.assertEqual(image.read_bytes(), self.assignments[role].read_bytes())
        self.assertEqual(old.get('rest').fit_mode, 'crop')
        self.assertEqual(old.get('rest').alignment, 'bottom')

    def test_one_source_can_be_explicitly_reused_for_all_roles(self):
        source = self.assignments['default']
        created = self.store.create('한 그림', {role: source for role in ROLES})
        self.assertEqual(len(set(created.images.values())), 10)
        self.assertTrue(all(path.read_bytes() == source.read_bytes() for path in created.images.values()))

    def test_same_names_case_unicode_and_whitespace_get_unique_suffixes(self):
        original = self.store.create('Café  세트', self.assignments)
        before = self.snapshot()
        second = self.store.create('  CAFE\u0301\t세트 ', self.assignments)
        third = self.store.create('café 세트', self.assignments)
        self.assertEqual((original.name, second.name, third.name), ('Café 세트', 'CAFÉ 세트 (2)', 'café 세트 (3)'))
        self.assertEqual(len({original.id, second.id, third.id}), 3)
        for path, content in before.items():
            self.assertEqual((self.base / path).read_bytes(), content)

    def test_name_limits_controls_and_suffix_length(self):
        for invalid in ('', ' \n ', 'x' * 81, 'bad\0name', 'bad\u202ename', None):
            with self.subTest(name=invalid), self.assertRaises(ValueError):
                self.store.preview(invalid, self.assignments)
        self.assertFalse(self.root.exists())
        self.store.create('x' * 80, self.assignments)
        second = self.store.create('x' * 80, self.assignments)
        self.assertEqual(len(second.name), 80)
        self.assertTrue(second.name.endswith(' (2)'))
        # The display name never becomes a path component.
        result = self.store.create('../사용자 이름: *?', self.assignments)
        self.assertTrue(all(path.parent.name == result.id[6:] for path in result.images.values()))

    def test_missing_extra_invalid_and_unreadable_sources_write_nothing(self):
        invalid = self.source / 'bad.png'
        invalid.write_bytes(b'not an image')
        cases = [dict(list(self.assignments.items())[:-1]),
                 {**self.assignments, 'extra': self.assignments['default']},
                 {**self.assignments, 'profile': invalid},
                 {**self.assignments, 'profile': self.source / 'missing.png'}]
        for assignments in cases:
            with self.subTest(assignments=assignments), self.assertRaises((ValueError, OSError)):
                self.store.preview('미완성', assignments)
        with patch.object(self.store, '_read_image', side_effect=PermissionError('unreadable source')):
            with self.assertRaises(PermissionError):
                self.store.preview('읽기 실패', self.assignments)
        self.assertFalse(self.root.exists())

    def test_source_change_after_preview_is_detected_even_with_preserved_timestamp(self):
        plan = self.store.preview('수정 전', self.assignments)
        source = self.assignments['profile']
        original_stat = source.stat()
        Image.new('RGB', (9, 12), 'red').save(source)
        os.utime(source, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '원본 이미지가 바뀌'):
            self.store.save(plan)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.list_sets(), ())

    def test_source_symlink_is_copy_only_and_retarget_requires_new_preview(self):
        link = self.source / 'selected.png'
        self.link(self.assignments['default'], link)
        assignments = {**self.assignments, 'default': link}
        created = self.store.create('연결 원본 복사', assignments)
        self.assertFalse(created.images['default'].is_symlink())
        plan = self.store.preview('변경된 연결', assignments)
        link.unlink()
        self.link(self.assignments['away'], link)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '원본 이미지 위치가 바뀌'):
            self.store.save(plan)
        self.assertEqual(self.snapshot(), before)

    def test_name_created_after_preview_requires_new_confirmation(self):
        plan = self.store.preview('같은 이름', self.assignments)
        self.store.create('같은 이름', self.assignments)
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '미리보기 이후 같은 이름'):
            self.store.save(plan)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.preview('같은 이름', self.assignments).name, '같은 이름 (2)')

    def test_existing_empty_folder_file_and_uuid_collision_are_never_overwritten(self):
        self.store.sets_dir.mkdir(parents=True)
        occupied = ['a' * 32, 'b' * 32, 'c' * 32]
        (self.store.sets_dir / occupied[0]).mkdir()
        (self.store.sets_dir / occupied[1]).write_bytes(b'existing file')
        (self.store.sets_dir / occupied[2].upper()).mkdir()
        fresh = 'd' * 32
        with patch('named_image_sets.uuid.uuid4', side_effect=[SimpleNamespace(hex=x) for x in [*occupied, fresh]]):
            result = self.store.create('충돌 없음', self.assignments)
        self.assertEqual(result.id, 'named:' + fresh)
        self.assertEqual(list((self.store.sets_dir / occupied[0]).iterdir()), [])
        self.assertEqual((self.store.sets_dir / occupied[1]).read_bytes(), b'existing file')
        self.assertTrue((self.store.sets_dir / occupied[2].upper()).is_dir())

    def test_uuid_mkdir_race_reserves_existing_empty_folder(self):
        first, second = 'a' * 32, 'b' * 32
        original_mkdir = Path.mkdir
        collided = self.store.sets_dir / first

        def racing_mkdir(path, *args, **kwargs):
            if path == collided and not path.exists():
                original_mkdir(path)
            return original_mkdir(path, *args, **kwargs)

        with patch('named_image_sets.uuid.uuid4', side_effect=[SimpleNamespace(hex=first), SimpleNamespace(hex=second)]), \
             patch.object(Path, 'mkdir', new=racing_mkdir):
            result = self.store.create('경쟁', self.assignments)
        self.assertEqual(result.id, 'named:' + second)
        self.assertTrue(collided.is_dir())
        self.assertEqual(list(collided.iterdir()), [])

    def test_id_exhaustion_preserves_reserved_directory(self):
        existing = self.store.sets_dir / ('a' * 32)
        existing.mkdir(parents=True)
        with patch('named_image_sets.uuid.uuid4', return_value=SimpleNamespace(hex='a' * 32)):
            with self.assertRaisesRegex(ValueError, 'ID를 만들지'):
                self.store.create('재시도', self.assignments)
        self.assertEqual(list(existing.iterdir()), [])

    def test_partial_writes_and_cancel_cleanup_only_this_attempt(self):
        original_set = self.store.create('기존', self.assignments)
        plan = self.store.preview('새 세트', self.assignments)
        before = self.snapshot()
        original_write = self.store._write_file
        for failure in (OSError('disk full'), KeyboardInterrupt()):
            count = 0

            def fail_fifth(path, content, owned):
                nonlocal count
                count += 1
                original_write(path, content, owned)
                if count == 5:
                    raise failure

            with self.subTest(failure=type(failure).__name__), patch.object(self.store, '_write_file', side_effect=fail_fifth):
                with self.assertRaises(type(failure)):
                    self.store.save(plan)
            self.assertEqual(self.snapshot(), before)
            self.assertEqual(self.store.list_sets(), (original_set,))

    def test_manifest_publication_failure_removes_new_images_and_preserves_existing(self):
        self.store.create('기존', self.assignments)
        before = self.snapshot()
        with patch('named_image_sets.os.link', side_effect=OSError('link unsupported')):
            with self.assertRaisesRegex(OSError, 'link unsupported'):
                self.store.create('새 세트', self.assignments)
        self.assertEqual(self.snapshot(), before)

    def test_manifest_race_preserves_other_writer_file(self):
        original_link = os.link
        preserved = []

        def racing_link(source, destination):
            destination.write_bytes(b'existing concurrent manifest')
            preserved.append(destination)
            return original_link(source, destination)

        with patch('named_image_sets.os.link', side_effect=racing_link):
            with self.assertRaises(FileExistsError):
                self.store.create('경쟁', self.assignments)
        self.assertEqual(preserved[0].read_bytes(), b'existing concurrent manifest')
        self.assertEqual(list(preserved[0].parent.iterdir()), preserved)

    def test_sets_are_not_visible_until_complete_manifest_is_published(self):
        original_write = self.store._write_file
        observations = []

        def observe(path, content, owned):
            original_write(path, content, owned)
            observations.append(self.store.list_sets())

        with patch.object(self.store, '_write_file', side_effect=observe):
            result = self.store.create('원자 공개', self.assignments)
        self.assertEqual(observations, [()] * 11)
        self.assertEqual(self.store.list_sets(), (result,))

    def test_store_path_symlinks_and_manifest_links_are_rejected(self):
        outside = self.base / 'outside'
        outside.mkdir()
        self.root.parent.mkdir(parents=True)
        self.link(outside, self.root, directory=True)
        with self.assertRaisesRegex(ValueError, '연결된'):
            self.store.create('위험 경로', self.assignments)
        self.assertEqual(list(outside.iterdir()), [])

    def test_lock_contention_fails_without_duplicate_names_then_recovers(self):
        plan = self.store.preview('동시 저장', self.assignments)
        with self.store._write_lock():
            with self.assertRaisesRegex(ValueError, '다른 세트 저장'):
                NamedImageSetStore(self.root).save(plan)
        self.assertEqual(self.store.list_sets(), ())
        self.assertEqual(self.store.save(plan).name, '동시 저장')

    def test_corrupt_future_and_incomplete_sets_are_not_selectable_and_names_stay_reserved(self):
        healthy = self.store.create('정상', self.assignments)
        corrupt = self.store.create('손상 이미지', self.assignments)
        corrupt.images['profile'].write_bytes(b'damaged')
        future = self.store.create('미래 세트', self.assignments)
        future_manifest = json.loads(self.manifest(future).read_text(encoding='utf-8'))
        future_manifest['schema_version'] = 999
        self.manifest(future).write_text(json.dumps(future_manifest, ensure_ascii=False), encoding='utf-8')
        (self.store.sets_dir / ('f' * 32)).mkdir()
        self.assertEqual(self.store.list_sets(), (healthy,))
        self.assertIsNone(self.store.get(corrupt.id))
        self.assertIsNone(self.store.get(future.id))
        self.assertEqual(self.store.preview('손상 이미지', self.assignments).name, '손상 이미지 (2)')
        self.assertEqual(self.store.preview('미래 세트', self.assignments).name, '미래 세트 (2)')
        self.manifest(corrupt).write_bytes(b'{broken json')
        before = self.snapshot()
        with self.assertRaisesRegex(ValueError, '기존 이름 세트 기록'):
            self.store.create('새 이름', self.assignments)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.store.list_sets(), (healthy,))

    def test_existing_manifest_read_failure_blocks_save_without_resetting_it(self):
        existing = self.store.create('읽기 실패', self.assignments)
        before = self.snapshot()
        with patch('named_image_sets._read_manifest', side_effect=PermissionError('unreadable manifest')):
            with self.assertRaisesRegex(ValueError, '기존 이름 세트 기록'):
                self.store.create('다른 이름', self.assignments)
        self.assertEqual(self.snapshot(), before)
        self.assertIsNotNone(self.store.get(existing.id))

    def test_manifest_validation_rejects_paths_roles_ids_hashes_and_versions(self):
        image_set = self.store.create('검증', self.assignments)
        original = json.loads(self.manifest(image_set).read_text(encoding='utf-8'))
        self.assertEqual(validate_manifest(original, image_set.id), original)
        invalid = []
        for filename in ('../default.png', '/default.png', r'C:\default.png', r'\\host\default.png',
                         'default.png:secret', '../' + 'a' * 32 + '/default.png', 'away.png', []):
            value = deepcopy(original)
            value['images']['default']['file'] = filename
            invalid.append(value)
        for field, replacement in (('schema_version', 2), ('schema_version', True), ('id', 'named:../../outside'),
                                    ('name', ' name '), ('images', {'default': original['images']['default']})):
            value = deepcopy(original); value[field] = replacement; invalid.append(value)
        for field, replacement in (('sha256', 'wrong'), ('bytes', True), ('bytes', 0), ('bytes', named.MAX_IMAGE_BYTES + 1)):
            value = deepcopy(original); value['images']['default'][field] = replacement; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_manifest(value, image_set.id)
        with self.assertRaises(ValueError):
            validate_manifest(original, 'named:' + '0' * 32)

    def test_missing_hash_changed_and_linked_saved_images_are_not_resolved(self):
        first = self.store.create('손상 확인', self.assignments)
        path = first.images['default']
        old_stat = path.stat()
        content = path.read_bytes()
        path.write_bytes(content[:-1] + bytes([content[-1] ^ 1]))
        os.utime(path, ns=(old_stat.st_atime_ns, old_stat.st_mtime_ns))
        self.assertIsNone(self.store.resolve(first.id, 'default'))
        path.unlink()
        self.assertIsNone(self.store.get(first.id))
        self.link(self.assignments['default'], path)
        self.assertIsNone(self.store.get(first.id))
        path.unlink(); path.write_bytes(content)
        metadata = self.manifest(first)
        external = self.base / 'external.json'
        external.write_bytes(metadata.read_bytes()); metadata.unlink()
        self.link(external, metadata)
        self.assertIsNone(self.store.get(first.id))

    def test_duplicate_json_keys_and_invalid_selection_do_not_resolve(self):
        result = self.store.create('중복 키', self.assignments)
        path = self.manifest(result)
        content = path.read_text(encoding='utf-8')
        path.write_text(content.replace('"schema_version": 1,', '"schema_version": 1, "schema_version": 1,'), encoding='utf-8')
        self.assertIsNone(self.store.get(result.id))
        for value in ('named:../outside', 'named:' + 'A' * 32, 'pack:01', '', None):
            self.assertIsNone(self.store.get(value))
        self.assertIsNone(self.store.resolve(result.id, 'not-a-role'))

    def test_plan_for_another_store_or_incomplete_plan_is_rejected(self):
        plan = self.store.preview('원래 위치', self.assignments)
        with self.assertRaises(ValueError):
            NamedImageSetStore(self.base / 'another').save(plan)
        with self.assertRaises(ValueError):
            self.store.save(replace(plan, images=plan.images[:-1]))
        self.assertFalse(self.root.exists())


if __name__ == '__main__':
    unittest.main()
