from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

# state.py
p = ROOT / "state.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, "SCHEMA_VERSION = 6\n", "SCHEMA_VERSION = 7\n", "state schema")
s = replace_once(
    s,
    "    longest_continuous_today: float = 0.0\n",
    "    longest_continuous_today: float = 0.0\n    break_reminders_suppressed: bool = False\n",
    "daily suppression field",
)
s = replace_once(
    s,
    '_BOOL_FIELDS = {"is_away", "manual_away"}\n',
    '_BOOL_FIELDS = {"is_away", "manual_away", "break_reminders_suppressed"}\n',
    "bool coercion",
)
p.write_text(s, encoding="utf-8")

# app.py
p = ROOT / "app.py"
s = p.read_text(encoding="utf-8")
old = '''    def snooze_break(self):
        mode = self._current_workday_state().mode
'''
new = '''    def suppress_break_reminders_today(self):
        self.state.daily.break_reminders_suppressed = True
        self.break_gate.reset()
        self._destroy_toast()
        save_state(STATE_FILE, self.state)
        text = "알겠어. 오늘은 휴식 알림은 그만할게. 내일 다시 챙길게."
        self._say("playful", text)
        self.show_toast(text)
        self._update_ui()

    def snooze_break(self):
        mode = self._current_workday_state().mode
'''
s = replace_once(s, old, new, "suppress method")
s = replace_once(
    s,
    '''            if not self.preferences.break_reminders:
                self.break_gate.reset()
            elif self.break_gate.should_show(result.break_due, now):
''',
    '''            if not self.preferences.break_reminders or self.state.daily.break_reminders_suppressed:
                self.break_gate.reset()
            elif self.break_gate.should_show(result.break_due, now):
''',
    "tick suppression gate",
)
s = replace_once(
    s,
    '''        if allow_snooze:
            self._button(row, "5분 더", self.snooze_break).pack(side="left")
''',
    '''        if allow_snooze:
            self._button(row, f"{self.preferences.snooze_minutes}분 더", self.snooze_break).pack(side="left", padx=(0, 6))
        self._button(row, "오늘은 그만", self.suppress_break_reminders_today).pack(side="left")
''',
    "toast controls",
)
s = replace_once(
    s,
    '''        self.remain.configure(text=fmt(remaining))
        self.next_break.configure(text=f"다음 휴식 알림: {fmt(remaining)} 후")
''',
    '''        if d.break_reminders_suppressed:
            self.remain.configure(text="오늘 꺼짐")
            self.next_break.configure(text="오늘 휴식 알림: 꺼짐")
        else:
            self.remain.configure(text=fmt(remaining))
            self.next_break.configure(text=f"다음 휴식 알림: {fmt(remaining)} 후")
''',
    "base UI suppression status",
)
p.write_text(s, encoding="utf-8")

# tests/test_state.py
p = ROOT / "tests" / "test_state.py"
s = p.read_text(encoding="utf-8")
anchor = '''    def test_midnight_away_is_counted_as_one_ongoing_away(self):
'''
new_tests = '''    def test_midnight_clears_daily_break_suppression(self):
        state = PersistedState(
            7,
            DailyStats(day="2026-09-02", break_reminders_suppressed=True),
            SessionState(continuous_seconds=1200),
        )
        rollover_daily(state, today="2026-09-03")
        self.assertEqual(state.daily.day, "2026-09-03")
        self.assertFalse(state.daily.break_reminders_suppressed)
        self.assertEqual(state.session.continuous_seconds, 1200)

    def test_break_suppression_roundtrips_in_state_file(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "state.json"
            state = PersistedState(
                7,
                DailyStats(day="2026-09-04", break_reminders_suppressed=True),
                SessionState(),
            )
            save_state(path, state, now_wall=1000)
            loaded = load_state(path)
            self.assertTrue(loaded.daily.break_reminders_suppressed)

'''
s = replace_once(s, anchor, new_tests + anchor, "state suppression tests")
p.write_text(s, encoding="utf-8")

# PHASE6_HANDOFF.md
p = ROOT / "PHASE6_HANDOFF.md"
s = p.read_text(encoding="utf-8")
s = s.replace(
    "ACTIVE / BREAK AND SNOOZE INTERVAL SETTINGS INTEGRATED.",
    "ACTIVE / BREAK INTERVAL, SNOOZE, AND TODAY-SUPPRESSION INTEGRATED.",
    1,
)
s = s.replace(
    "3. “Stop reminders for today” with a clear reset at the next workday/day boundary.",
    "3. “Stop reminders for today” integrated as daily persisted state; it resets automatically on the next local day rollover.",
    1,
)
p.write_text(s, encoding="utf-8")

print("Phase 6 suppress-today behavior applied")
