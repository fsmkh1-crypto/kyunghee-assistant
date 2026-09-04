from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


settings = Path('settings.py')
s = settings.read_text(encoding='utf-8')
s = replace_once(
    s,
    'PERSONALITIES = {"balanced", "warm", "playful", "strict"}\n',
    'PERSONALITIES = {"balanced", "warm", "playful", "strict"}\nMAX_CUSTOM_DIALOGUE_LINES = 30\nMAX_CUSTOM_DIALOGUE_LINE_LENGTH = 120\n',
    'settings constants',
)
insert_anchor = '''\ndef _fit_mode(value: object) -> str:\n'''
insert = '''\ndef normalize_custom_dialogue(value: object) -> str:\n    lines = [line.strip() for line in str(value or "").splitlines() if line.strip()]\n    if len(lines) > MAX_CUSTOM_DIALOGUE_LINES:\n        lines = lines[:MAX_CUSTOM_DIALOGUE_LINES]\n    return "\\n".join(line[:MAX_CUSTOM_DIALOGUE_LINE_LENGTH] for line in lines)\n\n\ndef validate_custom_dialogue(value: str) -> None:\n    lines = [line for line in str(value).splitlines() if line.strip()]\n    if len(lines) > MAX_CUSTOM_DIALOGUE_LINES:\n        raise ValueError(f"커스텀 대사는 최대 {MAX_CUSTOM_DIALOGUE_LINES}줄까지 사용할 수 있습니다.")\n    if any(len(line) > MAX_CUSTOM_DIALOGUE_LINE_LENGTH for line in lines):\n        raise ValueError(f"커스텀 대사는 한 줄 {MAX_CUSTOM_DIALOGUE_LINE_LENGTH}자까지 사용할 수 있습니다.")\n\n'''
s = replace_once(s, insert_anchor, insert + insert_anchor, 'settings custom helpers')
s = replace_once(
    s,
    '    personality: str = "balanced"\n\n    time_text_size: int = 16\n',
    '    personality: str = "balanced"\n    custom_dialogue: str = ""\n\n    time_text_size: int = 16\n',
    'settings field',
)
s = replace_once(
    s,
    '        if self.personality not in PERSONALITIES:\n            raise ValueError("경희 말투 설정이 올바르지 않습니다.")\n',
    '        if self.personality not in PERSONALITIES:\n            raise ValueError("경희 말투 설정이 올바르지 않습니다.")\n        validate_custom_dialogue(self.custom_dialogue)\n',
    'settings validation',
)
s = replace_once(
    s,
    '        personality=_personality(raw.get("personality", d.personality)),\n',
    '        personality=_personality(raw.get("personality", d.personality)),\n        custom_dialogue=normalize_custom_dialogue(raw.get("custom_dialogue", d.custom_dialogue)),\n',
    'settings parse',
)
settings.write_text(s, encoding='utf-8')


messages = Path('messages.py')
m = messages.read_text(encoding='utf-8')
anchor = '''\ndef maybe_pick_rare(\n'''
helper = '''\ndef custom_dialogue_lines(value: str) -> list[str]:\n    return [line.strip() for line in str(value or "").splitlines() if line.strip()]\n\n\ndef maybe_pick_custom(value: str, *, chance: float = 0.25, roll: float | None = None) -> str | None:\n    lines = custom_dialogue_lines(value)\n    if not lines:\n        return None\n    sample = random.random() if roll is None else float(roll)\n    if sample >= max(0.0, min(1.0, float(chance))):\n        return None\n    candidates = [line for line in lines if line not in _recent[-10:]] or lines\n    msg = random.choice(candidates)\n    _recent.append(msg)\n    if len(_recent) > 40:\n        del _recent[:-25]\n    return msg\n\n'''
m = replace_once(m, anchor, helper + anchor, 'messages custom helper')
messages.write_text(m, encoding='utf-8')


desktop = Path('desktop_compact.py')
d = desktop.read_text(encoding='utf-8')
d = replace_once(
    d,
    'from messages import habit_dialogue_kind, maybe_pick_rare, pick, time_of_day_kind\n',
    'from messages import habit_dialogue_kind, maybe_pick_custom, maybe_pick_rare, pick, time_of_day_kind\n',
    'desktop import custom',
)
ui_anchor = '''        self._label(\n            content,\n            "휴식·퇴근 경고 강도는 그대로 유지하고 평상시/응원/클릭 반응의 말투만 바뀝니다.",\n            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",\n        ).pack(anchor="w", pady=(0, 4), **pad)\n\n'''
ui_new = ui_anchor + '''        self._label(content, "내 대사", size=9, bg=core.PANEL).pack(anchor="w", pady=(6, 2), **pad)\n        self._label(\n            content,\n            "한 줄에 한 문장씩 입력하면 평상시 대사에 가끔 섞입니다. 중요한 휴식·퇴근 알림에는 사용되지 않습니다.",\n            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",\n        ).pack(anchor="w", pady=(0, 3), **pad)\n        self.custom_dialogue_text = tk.Text(\n            content, height=5, wrap="word",\n            font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL_2,\n            insertbackground=core.TEXT, relief="flat", bd=0, padx=7, pady=6,\n        )\n        self.custom_dialogue_text.pack(fill="x", pady=(0, 4), **pad)\n        if p.custom_dialogue:\n            self.custom_dialogue_text.insert("1.0", p.custom_dialogue)\n\n'''
d = replace_once(d, ui_anchor, ui_new, 'desktop custom UI')
d = replace_once(
    d,
    '                personality=self._personality_values.get(self.personality_var.get(), "balanced"),\n',
    '                personality=self._personality_values.get(self.personality_var.get(), "balanced"),\n                custom_dialogue=self.custom_dialogue_text.get("1.0", "end").strip(),\n',
    'desktop save custom',
)
old = '''            if habit_kind:\n                kind = habit_kind\n            else:\n                kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n                rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))\n                if rare:\n                    self.speech.configure(text=rare)\n                    self.last_dialogue_at = __import__("time").monotonic()\n                    self._apply_widget_appearance()\n                    return\n'''
new = '''            if habit_kind:\n                kind = habit_kind\n            else:\n                custom = maybe_pick_custom(getattr(self.preferences, "custom_dialogue", ""))\n                if custom:\n                    self.speech.configure(text=custom)\n                    self.last_dialogue_at = __import__("time").monotonic()\n                    self._apply_widget_appearance()\n                    return\n                kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n                rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))\n                if rare:\n                    self.speech.configure(text=rare)\n                    self.last_dialogue_at = __import__("time").monotonic()\n                    self._apply_widget_appearance()\n                    return\n'''
d = replace_once(d, old, new, 'desktop custom selection')
desktop.write_text(d, encoding='utf-8')


test_settings = Path('tests/test_settings.py')
ts = test_settings.read_text(encoding='utf-8')
marker = '''    def test_bad_widget_scale_falls_back(self):\n        parsed = settings_from_dict({"widget_scale": 500})\n        self.assertEqual(parsed.widget_scale, UserSettings().widget_scale)\n'''
extra = marker + '''\n    def test_custom_dialogue_normalizes_and_round_trips(self):\n        parsed = settings_from_dict({"custom_dialogue": " 첫 문장  \\n\\n둘째 문장 "})\n        self.assertEqual(parsed.custom_dialogue, "첫 문장\\n둘째 문장")\n        with tempfile.TemporaryDirectory() as directory:\n            path = Path(directory) / "settings.json"\n            save_user_settings(path, parsed)\n            self.assertEqual(load_user_settings(path).custom_dialogue, parsed.custom_dialogue)\n'''
ts = replace_once(ts, marker, extra, 'settings custom test')
test_settings.write_text(ts, encoding='utf-8')


test_messages = Path('tests/test_messages.py')
tm = test_messages.read_text(encoding='utf-8')
tm = replace_once(
    tm,
    '    habit_dialogue_kind,\n',
    '    custom_dialogue_lines,\n    habit_dialogue_kind,\n    maybe_pick_custom,\n',
    'messages custom test imports',
)
marker2 = '''    def test_habit_dialogue_priorities(self):\n'''
extra2 = '''    def test_custom_dialogue_selection(self):\n        value = "첫 문장\\n둘째 문장"\n        self.assertEqual(custom_dialogue_lines(value), ["첫 문장", "둘째 문장"])\n        self.assertIsNone(maybe_pick_custom(value, chance=0.25, roll=0.9))\n        self.assertIn(maybe_pick_custom(value, chance=0.25, roll=0.0), {"첫 문장", "둘째 문장"})\n\n'''
tm = replace_once(tm, marker2, extra2 + marker2, 'messages custom tests')
test_messages.write_text(tm, encoding='utf-8')
