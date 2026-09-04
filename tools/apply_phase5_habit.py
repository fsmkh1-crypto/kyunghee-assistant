from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


messages = Path('messages.py')
text = messages.read_text(encoding='utf-8')
anchor = '''\ndef time_of_day_kind(hour: int) -> str:\n'''
insert = '''\ndef habit_dialogue_kind(\n    *,\n    away_count: int,\n    longest_continuous: float,\n    continuous_seconds: float,\n) -> str | None:\n    \"\"\"Choose a lightweight habit reaction from already-recorded timer stats.\"\"\"\n    continuous = max(0.0, float(continuous_seconds))\n    longest = max(0.0, float(longest_continuous))\n    breaks = max(0, int(away_count))\n    if continuous >= 75 * 60:\n        return "nag"\n    if breaks >= 3 and longest <= 75 * 60:\n        return "praise"\n    if continuous >= 50 * 60:\n        return "worry"\n    return None\n\n'''
text = replace_once(text, anchor, insert + anchor, 'messages habit helper')
messages.write_text(text, encoding='utf-8')


desktop = Path('desktop_compact.py')
d = desktop.read_text(encoding='utf-8')
d = replace_once(
    d,
    'from messages import maybe_pick_rare, pick, time_of_day_kind\n',
    'from messages import habit_dialogue_kind, maybe_pick_rare, pick, time_of_day_kind\n',
    'desktop habit import',
)
old = '''        else:\n            remaining = self.engine.remaining_to_break()\n            kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n            rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))\n            if rare:\n                self.speech.configure(text=rare)\n                self.last_dialogue_at = __import__("time").monotonic()\n                self._apply_widget_appearance()\n                return\n'''
new = '''        else:\n            remaining = self.engine.remaining_to_break()\n            habit_kind = habit_dialogue_kind(\n                away_count=self.state.daily.away_count,\n                longest_continuous=self.state.daily.longest_continuous_today,\n                continuous_seconds=self.state.session.continuous_seconds,\n            )\n            if habit_kind:\n                kind = habit_kind\n            else:\n                kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n                rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))\n                if rare:\n                    self.speech.configure(text=rare)\n                    self.last_dialogue_at = __import__("time").monotonic()\n                    self._apply_widget_appearance()\n                    return\n'''
d = replace_once(d, old, new, 'desktop habit selection')
desktop.write_text(d, encoding='utf-8')


test = Path('tests/test_messages.py')
t = test.read_text(encoding='utf-8')
t = replace_once(
    t,
    '    RARE_POOLS,\n',
    '    RARE_POOLS,\n    habit_dialogue_kind,\n',
    'test import habit',
)
marker = '''    def test_unknown_personality_falls_back_to_balanced(self):\n        _reset_rare_state_for_tests()\n        self.assertIn(maybe_pick_rare("unknown", chance=1.0, roll=0.0), RARE_POOLS["balanced"])\n'''
extra = marker + '''\n    def test_habit_dialogue_priorities(self):\n        self.assertEqual(\n            habit_dialogue_kind(away_count=5, longest_continuous=2000, continuous_seconds=4600),\n            "nag",\n        )\n        self.assertEqual(\n            habit_dialogue_kind(away_count=3, longest_continuous=4000, continuous_seconds=1200),\n            "praise",\n        )\n        self.assertEqual(\n            habit_dialogue_kind(away_count=1, longest_continuous=5000, continuous_seconds=3100),\n            "worry",\n        )\n        self.assertIsNone(\n            habit_dialogue_kind(away_count=1, longest_continuous=1800, continuous_seconds=1200)\n        )\n'''
t = replace_once(t, marker, extra, 'habit tests')
test.write_text(t, encoding='utf-8')
