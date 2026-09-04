from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

# settings.py
p = ROOT / 'settings.py'; s = p.read_text(encoding='utf-8')
s = replace_once(s, '    schema_version: int = 6\n', '    schema_version: int = 7\n', 'schema')
s = replace_once(s, '    break_interval_minutes: int = 60\n    workday_reminders: bool = True\n', '    break_interval_minutes: int = 60\n    snooze_minutes: int = 5\n    workday_reminders: bool = True\n', 'snooze field')
s = replace_once(s, '        if not 20 <= self.break_interval_minutes <= 180:\n            raise ValueError("휴식 알림 간격은 20~180분 사이로 설정해 주세요.")\n', '        if not 20 <= self.break_interval_minutes <= 180:\n            raise ValueError("휴식 알림 간격은 20~180분 사이로 설정해 주세요.")\n        if not 1 <= self.snooze_minutes <= 30:\n            raise ValueError("미루기 시간은 1~30분 사이로 설정해 주세요.")\n', 'snooze validation')
s = replace_once(s, '        break_interval_minutes=_bounded_int(raw.get("break_interval_minutes"), d.break_interval_minutes, 20, 180),\n        workday_reminders=', '        break_interval_minutes=_bounded_int(raw.get("break_interval_minutes"), d.break_interval_minutes, 20, 180),\n        snooze_minutes=_bounded_int(raw.get("snooze_minutes"), d.snooze_minutes, 1, 30),\n        workday_reminders=', 'snooze load')
p.write_text(s, encoding='utf-8')

# timer_engine.py
p = ROOT / 'timer_engine.py'; s = p.read_text(encoding='utf-8')
s = replace_once(s, '    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None, break_interval_sec=BREAK_INTERVAL_SEC):\n        self.state = persisted_state\n        self.break_interval_sec = max(1.0, float(break_interval_sec))\n', '    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None, break_interval_sec=BREAK_INTERVAL_SEC, snooze_sec=SNOOZE_SEC):\n        self.state = persisted_state\n        self.break_interval_sec = max(1.0, float(break_interval_sec))\n        self.snooze_sec = max(1.0, float(snooze_sec))\n', 'engine snooze init')
s = replace_once(s, '    def remaining_to_break(self) -> float:\n', '    def set_snooze_interval(self, seconds: float) -> None:\n        self.snooze_sec = max(1.0, float(seconds))\n\n    def remaining_to_break(self) -> float:\n', 'snooze setter')
s = replace_once(s, '        s.next_break_at = s.continuous_seconds + SNOOZE_SEC\n', '        s.next_break_at = s.continuous_seconds + self.snooze_sec\n', 'snooze use')
p.write_text(s, encoding='utf-8')

# app.py
p = ROOT / 'app.py'; s = p.read_text(encoding='utf-8')
s = replace_once(s, '            break_interval_sec=self.preferences.break_interval_minutes * 60,\n        )\n', '            break_interval_sec=self.preferences.break_interval_minutes * 60,\n            snooze_sec=self.preferences.snooze_minutes * 60,\n        )\n', 'app snooze init')
s = replace_once(s, '        self.engine.set_break_interval(preferences.break_interval_minutes * 60)\n        self.root.attributes', '        self.engine.set_break_interval(preferences.break_interval_minutes * 60)\n        self.engine.set_snooze_interval(preferences.snooze_minutes * 60)\n        self.root.attributes', 'app snooze apply')
p.write_text(s, encoding='utf-8')

# desktop_compact.py
p = ROOT / 'desktop_compact.py'; s = p.read_text(encoding='utf-8')
marker = '''        self._label(content, "20~180분 · 기본 60분", size=8, fg=core.MUTED, bg=core.PANEL).pack(
            anchor="e", pady=(0, 3), **pad
        )

'''
ui = marker + '''        snooze_row = tk.Frame(content, bg=core.PANEL)
        snooze_row.pack(fill="x", pady=(3, 2), **pad)
        self._label(snooze_row, "미루기 시간(분)", size=9, bg=core.PANEL).pack(side="left")
        self.snooze_minutes_var = tk.StringVar(value=str(p.snooze_minutes))
        tk.Entry(
            snooze_row, textvariable=self.snooze_minutes_var, width=6, justify="center",
            font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL_2,
            insertbackground=core.TEXT, relief="flat", bd=0,
        ).pack(side="right", ipady=2)
        self._label(content, "1~30분 · 기본 5분", size=8, fg=core.MUTED, bg=core.PANEL).pack(
            anchor="e", pady=(0, 3), **pad
        )

'''
s = replace_once(s, marker, ui, 'compact snooze UI')
s = replace_once(s, '                break_interval_minutes=int(self.break_interval_var.get()),\n                workday_reminders=', '                break_interval_minutes=int(self.break_interval_var.get()),\n                snooze_minutes=int(self.snooze_minutes_var.get()),\n                workday_reminders=', 'compact snooze save')
p.write_text(s, encoding='utf-8')

# tests settings
p = ROOT/'tests'/'test_settings.py'; s = p.read_text(encoding='utf-8')
s = replace_once(s, '            break_interval_minutes=45,\n            wind_down=', '            break_interval_minutes=45,\n            snooze_minutes=8,\n            wind_down=', 'roundtrip snooze')
anchor = '    def test_break_interval_validation(self):\n'
newtests = '''    def test_snooze_minutes_loads_and_bad_value_falls_back(self):
        self.assertEqual(settings_from_dict({"snooze_minutes": 12}).snooze_minutes, 12)
        self.assertEqual(settings_from_dict({"snooze_minutes": 45}).snooze_minutes, UserSettings().snooze_minutes)

    def test_snooze_minutes_validation(self):
        with self.assertRaises(ValueError):
            UserSettings(snooze_minutes=0).validate_widget_style()

'''
s = replace_once(s, anchor, newtests + anchor, 'snooze settings tests')
p.write_text(s, encoding='utf-8')

# tests engine
p = ROOT/'tests'/'test_timer_engine.py'; s = p.read_text(encoding='utf-8')
anchor = '    def test_snooze_is_exactly_five_minutes(self):\n'
newtests = '''    def test_custom_snooze_interval(self):
        e = FakeEnv(); s = new_state()
        eng = TimerEngine(s, clock=e.clock, wall=e.wall_clock, idle_provider=e.idle_provider, snooze_sec=8 * 60)
        s.session.continuous_seconds = 3600
        eng.snooze_break()
        self.assertEqual(s.session.next_break_at, 4080)

    def test_changing_snooze_interval_affects_next_snooze(self):
        _, s, eng = self.make()
        eng.set_snooze_interval(12 * 60)
        s.session.continuous_seconds = 3600
        eng.snooze_break()
        self.assertEqual(s.session.next_break_at, 4320)

'''
s = replace_once(s, anchor, newtests + anchor, 'snooze engine tests')
p.write_text(s, encoding='utf-8')

# handoff
p = ROOT/'PHASE6_HANDOFF.md'; s = p.read_text(encoding='utf-8')
s = s.replace('ACTIVE / CONFIGURABLE BREAK INTERVAL INTEGRATION IN PROGRESS.', 'ACTIVE / BREAK AND SNOOZE INTERVAL SETTINGS INTEGRATED.', 1)
p.write_text(s, encoding='utf-8')
print('Phase 6 configurable snooze applied')
