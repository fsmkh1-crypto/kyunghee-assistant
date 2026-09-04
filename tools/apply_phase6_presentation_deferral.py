from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

# break_reminder.py
p = ROOT / "break_reminder.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''    def reset(self) -> None:
        self.armed = False
        self.last_shown_at = 0.0
''',
    '''    def defer(self) -> None:
        """Forget a hidden reminder so a still-due break can show immediately later."""
        self.armed = False
        self.last_shown_at = 0.0

    def reset(self) -> None:
        self.defer()
''',
    "gate defer",
)
p.write_text(s, encoding="utf-8")

# app.py: add hook and skip gate while presentation suppresses notifications
p = ROOT / "app.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''    def _current_workday_state(self) -> WorkdayState:
''',
    '''    def _break_notifications_suppressed(self) -> bool:
        return False

    def _current_workday_state(self) -> WorkdayState:
''',
    "base suppression hook",
)
s = replace_once(
    s,
    '''            if not self.preferences.break_reminders or self.state.daily.break_reminders_suppressed:
                self.break_gate.reset()
            elif self.break_gate.should_show(result.break_due, now):
''',
    '''            if not self.preferences.break_reminders or self.state.daily.break_reminders_suppressed:
                self.break_gate.reset()
            elif self._break_notifications_suppressed():
                pass
            elif self.break_gate.should_show(result.break_due, now):
''',
    "tick presentation skip",
)
p.write_text(s, encoding="utf-8")

# desktop_compact.py: hook native notification state and defer gate on transition in
p = ROOT / "desktop_compact.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '''    def _sync_presentation_state(self):
''',
    '''    def _break_notifications_suppressed(self) -> bool:
        return should_suppress_overlay_notifications()

    def _sync_presentation_state(self):
''',
    "compact suppression hook",
)
s = replace_once(
    s,
    '''            if suppressed:
                self.root.attributes("-topmost", False)
                self._destroy_toast()
''',
    '''            if suppressed:
                self.root.attributes("-topmost", False)
                self.break_gate.defer()
                self._destroy_toast()
''',
    "presentation defer",
)
p.write_text(s, encoding="utf-8")

# tests/test_break_reminder.py
p = ROOT / "tests" / "test_break_reminder.py"
s = p.read_text(encoding="utf-8")
anchor = '''    def test_not_due_never_arms(self):
'''
new_test = '''    def test_defer_rearms_still_due_break_immediately(self):
        gate = BreakReminderGate(repeat_interval_sec=300)
        self.assertTrue(gate.should_show(True, 100.0))
        gate.defer()
        self.assertFalse(gate.armed)
        self.assertTrue(gate.should_show(True, 101.0))

'''
s = replace_once(s, anchor, new_test + anchor, "deferral test")
p.write_text(s, encoding="utf-8")

# handoff
p = ROOT / "PHASE6_HANDOFF.md"
s = p.read_text(encoding="utf-8")
s = s.replace(
    "5. Ensure fullscreen/presentation deferral resumes reminders correctly.",
    "5. Fullscreen/presentation deferral integrated: hidden break reminders do not consume the repeat gate, and a still-due reminder can appear immediately after presentation mode ends.",
    1,
)
p.write_text(s, encoding="utf-8")

print("Phase 6 presentation deferral applied")
