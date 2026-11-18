"""Damaged numeric state and disabled-reminder regressions, no real profile/GUI."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from state import load_state, prepare_startup_state


class StateNumericHotfixTests(unittest.TestCase):
    def load(self, session, daily=None):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        path = Path(directory) / 'state.json'
        path.write_text(json.dumps({
            'daily': daily or {'day': '2026-11-17', 'active_seconds': 123},
            'session': session,
            'history': [{'day': '2026-11-16', 'active_seconds': 456}],
        }), encoding='utf-8')
        original = path.read_bytes()
        state = load_state(path)
        self.assertEqual(path.read_bytes(), original, 'Loading must not rewrite source data')
        self.assertEqual(state.history[0].active_seconds, 456)
        return state

    def test_null_last_seen_does_not_block_startup_or_discard_daily_history(self):
        state = self.load({'last_seen_wall': None})
        self.assertEqual(state.session.last_seen_wall, 0)
        prepare_startup_state(state, 1000, today='2026-11-17')
        self.assertEqual(state.daily.active_seconds, 123)
        self.assertEqual(state.history[0].active_seconds, 456)

    def test_invalid_required_numbers_use_field_defaults(self):
        for value in (None, 'bad', 'NaN', float('inf'), -1, {}, [], True):
            with self.subTest(value=value):
                state = self.load(dict.fromkeys((
                    'continuous_seconds', 'day_continuous_seconds',
                    'idle_candidate_seconds', 'last_seen_wall', 'next_break_at',
                ), value))
                self.assertEqual(state.session.continuous_seconds, 0)
                self.assertEqual(state.session.day_continuous_seconds, 0)
                self.assertEqual(state.session.idle_candidate_seconds, 0)
                self.assertEqual(state.session.last_seen_wall, 0)
                self.assertEqual(state.session.next_break_at, 3600)
                prepare_startup_state(state, 1000, today='2026-11-17')

    def test_optional_away_times_keep_null_and_valid_numeric_strings_are_preserved(self):
        state = self.load({'away_started_wall': None, 'away_started_mono': None,
                           'last_seen_wall': '990', 'continuous_seconds': '12.5',
                           'next_break_at': '4500', 'ignored_breaks': '2'})
        prepare_startup_state(state, 1000, today='2026-11-17')
        self.assertIsNone(state.session.away_started_wall)
        self.assertIsNone(state.session.away_started_mono)
        self.assertEqual(state.session.continuous_seconds, 12.5)
        self.assertEqual(state.session.next_break_at, 4500)
        self.assertEqual(state.session.ignored_breaks, 2)


    def test_negative_virtual_away_anchors_are_valid(self):
        state = self.load({'away_started_mono': -690, 'away_started_wall': -10,
                           'last_seen_wall': 990})
        self.assertEqual(state.session.away_started_mono, -690)
        self.assertEqual(state.session.away_started_wall, -10)

    def test_bad_counter_does_not_discard_other_valid_fields(self):
        state = self.load({'ignored_breaks': float('inf'), 'last_seen_wall': 990},
                          {'day': '2026-11-17', 'active_seconds': 123,
                           'away_seconds': None, 'away_count': float('inf')})
        self.assertEqual(state.daily.active_seconds, 123)
        self.assertEqual(state.daily.away_seconds, 0)
        self.assertEqual(state.daily.away_count, 0)
        self.assertEqual(state.session.ignored_breaks, 0)

    def test_null_session_preserves_valid_daily_and_history(self):
        state = self.load(None)
        self.assertEqual(state.daily.active_seconds, 123)
        prepare_startup_state(state, 1000, today='2026-11-17')


class ReminderDisplayHotfixTests(unittest.TestCase):
    def test_live_update_enabled_disabled_and_today_suppressed(self):
        # Isolate app's import-time logging and pystray backend from other tests.
        # No window is created; these widgets are test doubles.
        script = '''
from types import SimpleNamespace
from unittest.mock import Mock
from app import App
from state import fresh_state
state = fresh_state()
widgets = {name: Mock() for name in ('status', 'away_btn', 'cont', 'timer_caption',
    'remain', 'next_break', 'today_active', 'today_away', 'today_ratio')}
app = SimpleNamespace(state=state, preferences=SimpleNamespace(break_reminders=True),
    engine=SimpleNamespace(remaining_to_break=lambda: 3600),
    _update_progress=Mock(), **widgets)
for enabled, suppressed, remain, footer in (
    (True, False, '1시간 0분', '다음 휴식 알림: 1시간 0분 후'),
    (False, False, '꺼짐', '휴식 알림: 꺼짐'),
    (False, True, '꺼짐', '휴식 알림: 꺼짐'),
    (True, True, '오늘 꺼짐', '오늘 휴식 알림: 꺼짐'),
    (True, False, '1시간 0분', '다음 휴식 알림: 1시간 0분 후'),
):
    app.preferences.break_reminders = enabled
    state.daily.break_reminders_suppressed = suppressed
    App._update_ui(app)
    widgets['remain'].configure.assert_called_with(text=remain)
    widgets['next_break'].configure.assert_called_with(text=footer)
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, '-c', script],
                                    cwd=Path(__file__).resolve().parents[1],
                                    env=dict(os.environ, APPDATA=directory, PYSTRAY_BACKEND='dummy'),
                                    capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
