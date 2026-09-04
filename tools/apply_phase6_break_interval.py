from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

# settings.py
p = ROOT / "settings.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, '    schema_version: int = 5\n', '    schema_version: int = 6\n', 'schema version')
s = replace_once(
    s,
    '    break_reminders: bool = True\n    workday_reminders: bool = True\n',
    '    break_reminders: bool = True\n    break_interval_minutes: int = 60\n    workday_reminders: bool = True\n',
    'break setting field',
)
s = replace_once(
    s,
    '        if not 80 <= self.widget_scale <= 200:\n            raise ValueError("위젯 크기는 80~200% 사이로 설정해 주세요.")\n',
    '        if not 20 <= self.break_interval_minutes <= 180:\n            raise ValueError("휴식 알림 간격은 20~180분 사이로 설정해 주세요.")\n        if not 80 <= self.widget_scale <= 200:\n            raise ValueError("위젯 크기는 80~200% 사이로 설정해 주세요.")\n',
    'break validation',
)
s = replace_once(
    s,
    '        break_reminders=_coerce_bool(raw.get("break_reminders"), d.break_reminders),\n        workday_reminders=_coerce_bool(raw.get("workday_reminders"), d.workday_reminders),\n',
    '        break_reminders=_coerce_bool(raw.get("break_reminders"), d.break_reminders),\n        break_interval_minutes=_bounded_int(raw.get("break_interval_minutes"), d.break_interval_minutes, 20, 180),\n        workday_reminders=_coerce_bool(raw.get("workday_reminders"), d.workday_reminders),\n',
    'break settings load',
)
p.write_text(s, encoding="utf-8")

# timer_engine.py
p = ROOT / "timer_engine.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None):\n        self.state = persisted_state\n',
    '    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None, break_interval_sec=BREAK_INTERVAL_SEC):\n        self.state = persisted_state\n        self.break_interval_sec = max(1.0, float(break_interval_sec))\n',
    'engine init',
)
s = replace_once(
    s,
    '        self.manual_grace_until = 0.0\n\n    def remaining_to_break(self) -> float:\n',
    '        self.manual_grace_until = 0.0\n        if self.state.session.ignored_breaks == 0:\n            self.state.session.next_break_at = self.break_interval_sec\n\n    def set_break_interval(self, seconds: float) -> None:\n        self.break_interval_sec = max(1.0, float(seconds))\n        if self.state.session.ignored_breaks == 0:\n            self.state.session.next_break_at = self.break_interval_sec\n\n    def remaining_to_break(self) -> float:\n',
    'engine set interval',
)
s = replace_once(s, '        s.next_break_at = BREAK_INTERVAL_SEC\n', '        s.next_break_at = self.break_interval_sec\n', 'session reset interval')
p.write_text(s, encoding="utf-8")

# app.py
p = ROOT / "app.py"
s = p.read_text(encoding="utf-8")
s = replace_once(s, 'from timer_engine import BREAK_INTERVAL_SEC, TimerEngine\n', 'from timer_engine import TimerEngine\n', 'app import')
s = replace_once(
    s,
    '        self.engine = TimerEngine(self.state)\n',
    '        self.engine = TimerEngine(\n            self.state,\n            break_interval_sec=self.preferences.break_interval_minutes * 60,\n        )\n',
    'app engine init',
)
s = replace_once(
    s,
    '        self.workday_policy = preferences.workday_policy()\n        self.root.attributes("-topmost", preferences.always_on_top)\n',
    '        self.workday_policy = preferences.workday_policy()\n        self.engine.set_break_interval(preferences.break_interval_minutes * 60)\n        self.root.attributes("-topmost", preferences.always_on_top)\n',
    'apply preferences interval',
)
s = replace_once(
    s,
    '        progress = min(1.0, continuous / BREAK_INTERVAL_SEC)\n',
    '        target = max(1.0, float(self.state.session.next_break_at))\n        progress = min(1.0, continuous / target)\n',
    'progress interval',
)
p.write_text(s, encoding="utf-8")

# desktop_compact.py
p = ROOT / "desktop_compact.py"
s = p.read_text(encoding="utf-8")
marker = '''        self._label(content, "긴급 숨기기 단축키: Ctrl+Shift+H", size=8, fg=core.MUTED, bg=core.PANEL).pack(
            anchor="w", pady=(2, 2), **pad
        )
'''
interval_ui = '''        interval_row = tk.Frame(content, bg=core.PANEL)
        interval_row.pack(fill="x", pady=(5, 2), **pad)
        self._label(interval_row, "휴식 알림 간격(분)", size=9, bg=core.PANEL).pack(side="left")
        self.break_interval_var = tk.StringVar(value=str(p.break_interval_minutes))
        tk.Entry(
            interval_row,
            textvariable=self.break_interval_var,
            width=6,
            justify="center",
            font=(self.FONT_FAMILY, 9, "normal"),
            fg=core.TEXT,
            bg=core.PANEL_2,
            insertbackground=core.TEXT,
            relief="flat",
            bd=0,
        ).pack(side="right", ipady=2)
        self._label(content, "20~180분 · 기본 60분", size=8, fg=core.MUTED, bg=core.PANEL).pack(
            anchor="e", pady=(0, 3), **pad
        )

'''
s = replace_once(s, marker, interval_ui + marker, 'compact interval UI')
s = replace_once(
    s,
    '                break_reminders=self.settings_bool_vars["break_reminders"].get(),\n                workday_reminders=self.settings_bool_vars["workday_reminders"].get(),\n',
    '                break_reminders=self.settings_bool_vars["break_reminders"].get(),\n                break_interval_minutes=int(self.break_interval_var.get()),\n                workday_reminders=self.settings_bool_vars["workday_reminders"].get(),\n',
    'compact save interval',
)
p.write_text(s, encoding="utf-8")

# tests/test_settings.py
p = ROOT / "tests" / "test_settings.py"
s = p.read_text(encoding="utf-8")
s = replace_once(
    s,
    '            break_reminders=False,\n            wind_down="16:45",\n',
    '            break_reminders=False,\n            break_interval_minutes=45,\n            wind_down="16:45",\n',
    'settings roundtrip interval',
)
anchor = '    def test_bad_widget_scale_falls_back(self):\n'
newtests = '''    def test_break_interval_loads_and_bad_value_falls_back(self):
        self.assertEqual(settings_from_dict({"break_interval_minutes": 45}).break_interval_minutes, 45)
        self.assertEqual(
            settings_from_dict({"break_interval_minutes": 5}).break_interval_minutes,
            UserSettings().break_interval_minutes,
        )

    def test_break_interval_validation(self):
        with self.assertRaises(ValueError):
            UserSettings(break_interval_minutes=181).validate_widget_style()

'''
s = replace_once(s, anchor, newtests + anchor, 'settings interval tests')
p.write_text(s, encoding="utf-8")

# tests/test_timer_engine.py
p = ROOT / "tests" / "test_timer_engine.py"
s = p.read_text(encoding="utf-8")
anchor = '    def test_snooze_is_exactly_five_minutes(self):\n'
newtests = '''    def test_custom_break_interval(self):
        e = FakeEnv()
        s = new_state()
        eng = TimerEngine(
            s,
            clock=e.clock,
            wall=e.wall_clock,
            idle_provider=e.idle_provider,
            break_interval_sec=45 * 60,
        )
        s.session.continuous_seconds = 2699
        s.session.day_continuous_seconds = 2699
        e.advance(1, idle=0, input_event=True)
        self.assertTrue(eng.tick().break_due)

    def test_changing_interval_updates_unsnoozed_target(self):
        _, s, eng = self.make()
        eng.set_break_interval(40 * 60)
        self.assertEqual(s.session.next_break_at, 40 * 60)

    def test_changing_interval_preserves_active_snooze(self):
        _, s, eng = self.make()
        s.session.continuous_seconds = 3600
        eng.snooze_break()
        target = s.session.next_break_at
        eng.set_break_interval(40 * 60)
        self.assertEqual(s.session.next_break_at, target)
        eng.start_manual_away()
        self.assertEqual(s.session.next_break_at, 40 * 60)

'''
s = replace_once(s, anchor, newtests + anchor, 'timer interval tests')
p.write_text(s, encoding="utf-8")

# PHASE6_HANDOFF.md lightweight update
p = ROOT / "PHASE6_HANDOFF.md"
s = p.read_text(encoding="utf-8")
s = s.replace('ACTIVE / NOT YET IMPLEMENTED BEYOND EXISTING BASELINE.', 'ACTIVE / CONFIGURABLE BREAK INTERVAL INTEGRATION IN PROGRESS.', 1)
p.write_text(s, encoding="utf-8")

print('Phase 6 configurable break interval applied')
