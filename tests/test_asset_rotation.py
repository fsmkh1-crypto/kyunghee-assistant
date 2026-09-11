from pathlib import Path
import random
import tempfile
import unittest

from asset_rotation import (
    ROLE_FOLDERS,
    next_nonrepeating_ref,
    next_nonrepeating_set,
    raw_complete_sets,
    unique_complete_sets,
)


class AssetRotationTests(unittest.TestCase):
    def _make_assets(self, root: Path, count: int = 4):
        for role in ROLE_FOLDERS:
            folder = root / role
            folder.mkdir(parents=True, exist_ok=True)
            for number in range(1, count + 1):
                payload_number = 3 if number == 4 else number
                (folder / f'{role}_{number:02d}.png').write_bytes(f'{role}:{payload_number}'.encode())

    def test_raw_complete_sets_can_be_called_without_argument(self):
        # desktop_gallery_final installs this function as a drop-in replacement
        # for asset_manager.available_complete_sets(), whose callers use no args.
        result = raw_complete_sets()
        self.assertIsInstance(result, tuple)

    def test_identical_complete_set_is_collapsed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'assets'
            self._make_assets(root)
            self.assertEqual(unique_complete_sets(root), (1, 2, 3))

    def test_set_rotation_consumes_cycle_before_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / 'assets'
            self._make_assets(root)
            state = Path(temp) / 'set-state.json'
            values = [next_nonrepeating_set(root, state, rng=random.Random(7)) for _ in range(3)]
            self.assertEqual(len(set(values)), 3)

    def test_gallery_rotation_consumes_every_ref_before_repeat(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'gallery-state.json'
            refs = ['a', 'b', 'c', 'd']
            values = [next_nonrepeating_ref(refs, state, rng=random.Random(11)) for _ in refs]
            self.assertEqual(set(values), set(refs))


if __name__ == '__main__':
    unittest.main()
