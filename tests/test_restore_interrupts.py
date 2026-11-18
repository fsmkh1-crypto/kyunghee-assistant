"""Restore interruption tests use disposable profiles, never real user data."""
from dataclasses import asdict
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from settings import UserSettings
import user_data_backup as backup


class RestoreInterruptTests(unittest.TestCase):
    def fixture(self, root, *, existing=True):
        profile = root / 'profile'
        profile.mkdir()
        settings = profile / 'settings.json'
        settings.write_text(json.dumps(asdict(UserSettings(always_on_top=False))))
        archive = root / 'backup.zip'
        backup.create_backup(profile, archive, ('settings',))
        if existing:
            settings.write_text(json.dumps(asdict(UserSettings(always_on_top=True))))
            original = settings.read_bytes()
        else:
            settings.unlink()
            original = None
        return profile, archive, original

    def assert_original(self, profile, original):
        path = profile / 'settings.json'
        if original is None:
            self.assertFalse(path.exists())
        else:
            self.assertEqual(path.read_bytes(), original)
        self.assertFalse((profile / 'ai_settings.json').exists())
        self.assertEqual(backup.unfinished_restore_journals(profile), ())
        self.assertEqual(len(list((profile / 'backups').glob('*.zip'))), 1)

    def test_interruptions_before_and_after_each_replace_roll_back(self):
        for exception in (KeyboardInterrupt, SystemExit):
            for existing in (True, False):
                for stage in ('originals', 'staged'):
                    if stage == 'originals' and not existing:
                        continue
                    for after in (False, True):
                        for name in ('settings.json', 'ai_settings.json'):
                            if stage == 'originals' and name == 'ai_settings.json':
                                continue
                            with self.subTest(exception=exception, existing=existing, stage=stage, after=after, name=name):
                                with tempfile.TemporaryDirectory() as tmp:
                                    profile, archive, original = self.fixture(Path(tmp), existing=existing)
                                    replace = backup.os.replace
                                    fired = False
                                    def interrupt(src, dst):
                                        nonlocal fired
                                        matches = (Path(src).name == name and
                                            (Path(dst).parent.name == stage if stage == 'originals'
                                             else Path(src).parent.name == stage))
                                        if matches and not fired:
                                            fired = True
                                            if after:
                                                replace(src, dst)
                                            raise exception('injected interruption')
                                        return replace(src, dst)
                                    with patch.object(backup.os, 'replace', side_effect=interrupt):
                                        with self.assertRaises(exception):
                                            backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)
                                    self.assertTrue(fired)
                                    self.assert_original(profile, original)

    def test_directory_replacement_interruption_restores_original_tree(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / 'profile'
            images = profile / 'images'
            images.mkdir(parents=True)
            Image.new('RGB', (8, 8), 'red').save(images / 'new.png')
            archive = root / 'images.zip'
            backup.create_backup(profile, archive, ('images',))
            (images / 'new.png').unlink()
            Image.new('RGB', (8, 8), 'blue').save(images / 'original.png')
            original = (images / 'original.png').read_bytes()
            replace = backup.os.replace
            def interrupt(src, dst):
                result = replace(src, dst)
                if Path(src).name == 'images' and Path(src).parent.name == 'staged':
                    raise KeyboardInterrupt('directory replaced')
                return result
            with patch.object(backup.os, 'replace', side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore_backup(archive, profile, ('images',), app_is_quiescent=True)
            self.assertEqual((images / 'original.png').read_bytes(), original)
            self.assertFalse((images / 'new.png').exists())
            self.assertEqual(backup.unfinished_restore_journals(profile), ())

    def test_interrupted_rollback_preserves_journal_and_startup_guard(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, archive, original = self.fixture(Path(tmp))
            replace = backup.os.replace
            def interrupt(src, dst):
                if Path(src).name == 'settings.json':
                    if Path(src).parent.name == 'staged':
                        raise KeyboardInterrupt('apply interrupted')
                    if Path(src).parent.name == 'originals':
                        raise SystemExit('rollback interrupted')
                return replace(src, dst)
            with patch.object(backup.os, 'replace', side_effect=interrupt):
                with self.assertRaises(backup.RestoreRecoveryError) as caught:
                    backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)
            self.assertTrue(caught.exception.recovery_backup.is_file())
            journals = backup.unfinished_restore_journals(profile)
            self.assertEqual(len(journals), 1)
            self.assertEqual((journals[0] / 'originals/settings.json').read_bytes(), original)
            with self.assertRaisesRegex(backup.BackupError, '이전 복원'):
                backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)

    def test_abrupt_process_exit_leaves_original_and_blocks_another_restore(self):
        # An uncatchable process exit does not run finally. Never execute it
        # in the runner: restore only the generated disposable child profile.
        worker = """
import os, sys
from pathlib import Path
import user_data_backup as backup
archive, profile = map(Path, sys.argv[1:])
replace = os.replace
def stop_after_original_moved(src, dst):
    result = replace(src, dst)
    if Path(dst).name == 'settings.json' and Path(dst).parent.name == 'originals':
        os._exit(73)
    return result
backup.os.replace = stop_after_original_moved
backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)
"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile, archive, original = self.fixture(root)
            result = subprocess.run(
                [sys.executable, '-c', worker, str(archive), str(profile)],
                cwd=Path(__file__).resolve().parents[1],
                env=dict(os.environ, APPDATA=str(root / 'child-profile')),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
            )
            self.assertEqual(result.returncode, 73, result.stderr)
            pending = backup.unfinished_restore_journals(profile)
            self.assertEqual(len(pending), 1)
            self.assertEqual((pending[0] / 'originals/settings.json').read_bytes(), original)
            self.assertTrue((pending[0] / 'transaction.json').is_file())
            snapshots = list((profile / 'backups').glob('*.zip'))
            self.assertEqual(len(snapshots), 1)
            self.assertIn('settings', backup.inspect_backup(snapshots[0]).categories)
            with self.assertRaisesRegex(backup.BackupError, '이전 복원'):
                backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)

    def test_interrupt_at_commit_boundary(self):
        for after in (False, True):
            with self.subTest(after=after), tempfile.TemporaryDirectory() as tmp:
                profile, archive, original = self.fixture(Path(tmp))
                touch = Path.touch
                def interrupt(path, *args, **kwargs):
                    if path.name == 'committed':
                        if after:
                            touch(path, *args, **kwargs)
                        raise KeyboardInterrupt('commit interrupted')
                    return touch(path, *args, **kwargs)
                with patch.object(Path, 'touch', interrupt):
                    with self.assertRaises(KeyboardInterrupt):
                        backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)
                if after:
                    self.assertFalse(json.loads((profile / 'settings.json').read_text())['always_on_top'])
                    self.assertEqual(backup.unfinished_restore_journals(profile), ())
                else:
                    self.assert_original(profile, original)

    def test_interrupt_during_cleanup_never_rolls_back_committed_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            profile, archive, original = self.fixture(Path(tmp))
            rmtree = backup.shutil.rmtree
            def interrupt(path, *args, **kwargs):
                if Path(path).name.startswith('.restore-journal-'):
                    raise KeyboardInterrupt('cleanup interrupted')
                return rmtree(path, *args, **kwargs)
            with patch.object(backup.shutil, 'rmtree', side_effect=interrupt):
                with self.assertRaises(KeyboardInterrupt):
                    backup.restore_backup(archive, profile, ('settings',), app_is_quiescent=True)
            self.assertFalse(json.loads((profile / 'settings.json').read_text())['always_on_top'])
            self.assertEqual(backup.unfinished_restore_journals(profile), ())
            journal = next(profile.glob('.restore-journal-*'))
            self.assertEqual((journal / 'originals/settings.json').read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
