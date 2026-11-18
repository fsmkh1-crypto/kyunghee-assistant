from dataclasses import asdict
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from state import fresh_state, save_state, load_state, HISTORY_LIMIT
import user_data_backup as backup


class BackupIdleDaysTests(unittest.TestCase):
    def test_roundtrip_pending_midnight_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / 'source'
            source.mkdir()
            state = fresh_state()
            state.session.idle_candidate_days = {'2026-11-17': [179.0, 200.0], '2026-11-18': [121.0, 121.0]}
            state.session.idle_candidate_seconds = 300.0
            save_state(source / 'state.json', state, 1234)
            archive = root / 'backup.zip'
            backup.create_backup(source, archive, ('timer',))
            backup.restore_backup(archive, root / 'restored', ('timer',), app_is_quiescent=True)
            self.assertEqual(asdict(load_state(root / 'restored/state.json')), asdict(state))

    def test_old_backup_missing_map_defaults_empty(self):
        state = asdict(fresh_state())
        del state['session']['idle_candidate_days']
        clean = json.loads(backup._clean_json('state.json', json.dumps(state).encode()))
        self.assertEqual(clean['session']['idle_candidate_days'], {})

    def test_invalid_maps_rejected(self):
        invalid = [None, [], {'20261117': [1, 1]}, {'2026-02-30': [1, 1]},
                   {'2026-11-17': [1]}, {'2026-11-17': [1, 2, 3]},
                   {'2026-11-17': [True, 2]}, {'2026-11-17': ['1', 2]},
                   {'2026-11-17': [-1, 2]}, {'2026-11-17': [3, 2]},
                   {'2026-11-17': [1, 1e16]}, {'2026-11-17': [1, float('inf')]},
                   {'2026-11-17': [float('nan'), 2]},
                   {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): [0, 0]
                    for i in range(HISTORY_LIMIT + 2)}]
        for candidate in invalid:
            with self.subTest(candidate=candidate):
                state = asdict(fresh_state())
                state['session']['idle_candidate_days'] = candidate
                with self.assertRaises(backup.BackupError):
                    backup._clean_json('state.json', json.dumps(state).encode())

    def test_empty_and_full_bounded_maps_accepted(self):
        for candidate in ({}, {(date(2026, 1, 1) + timedelta(days=i)).isoformat(): [0, 1e15]
                              for i in range(HISTORY_LIMIT + 1)}):
            state = asdict(fresh_state())
            state['session']['idle_candidate_days'] = candidate
            clean = json.loads(backup._clean_json('state.json', json.dumps(state).encode()))
            self.assertEqual(clean['session']['idle_candidate_days'], candidate)


if __name__ == '__main__':
    unittest.main()
