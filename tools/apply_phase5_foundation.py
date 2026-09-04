from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)

# settings.py
p = Path('settings.py')
t = p.read_text(encoding='utf-8')
t = replace_once(t,
'''def _fit_mode(value: object) -> str:\n    return str(value) if str(value) in {"fit", "crop"} else "fit"\n''',
'''PERSONALITIES = {"balanced", "warm", "playful", "strict"}\n\n\ndef _personality(value: object) -> str:\n    value = str(value)\n    return value if value in PERSONALITIES else "balanced"\n\n\ndef _fit_mode(value: object) -> str:\n    return str(value) if str(value) in {"fit", "crop"} else "fit"\n''', 'settings helper')
t = replace_once(t,
'''class UserSettings:\n    schema_version: int = 4\n    start_with_windows: bool = False\n''',
'''class UserSettings:\n    schema_version: int = 5\n    start_with_windows: bool = False\n''', 'schema')
t = replace_once(t,
'''    show_message: bool = True\n\n    time_text_size: int = 16\n''',
'''    show_message: bool = True\n    personality: str = "balanced"\n\n    time_text_size: int = 16\n''', 'personality field')
t = replace_once(t,
'''        if not 9 <= self.message_text_size <= 16:\n            raise ValueError("메시지 글자 크기는 9~16 사이로 설정해 주세요.")\n        validate_hex_color(self.time_text_color)\n''',
'''        if not 9 <= self.message_text_size <= 16:\n            raise ValueError("메시지 글자 크기는 9~16 사이로 설정해 주세요.")\n        if self.personality not in PERSONALITIES:\n            raise ValueError("경희 말투 설정이 올바르지 않습니다.")\n        validate_hex_color(self.time_text_color)\n''', 'validate personality')
t = replace_once(t,
'''        show_message=_coerce_bool(raw.get("show_message"), d.show_message),\n        time_text_size=_bounded_int(raw.get("time_text_size"), d.time_text_size, 14, 24),\n''',
'''        show_message=_coerce_bool(raw.get("show_message"), d.show_message),\n        personality=_personality(raw.get("personality", d.personality)),\n        time_text_size=_bounded_int(raw.get("time_text_size"), d.time_text_size, 14, 24),\n''', 'load personality')
p.write_text(t, encoding='utf-8')

# messages.py
p = Path('messages.py')
t = p.read_text(encoding='utf-8')
t = replace_once(t,
'''    "hard_stop": [\n        "오늘 실사용 9시간이야. 이제는 진짜 끝내자.",\n        "9시간 채웠어. 더 하는 건 내가 반대야. 이제 가자.",\n        "오늘 충분히 했어. 여기서 업무 종료.",\n    ],\n}\n''',
'''    "hard_stop": [\n        "오늘 실사용 9시간이야. 이제는 진짜 끝내자.",\n        "9시간 채웠어. 더 하는 건 내가 반대야. 이제 가자.",\n        "오늘 충분히 했어. 여기서 업무 종료.",\n    ],\n    "click": [\n        "응, 나 눌렀어? 기록 보러 가자.",\n        "불렀어? 오늘 기록 같이 보자.",\n        "왜, 나 보고 싶었어? 일단 기록부터 확인.",\n        "클릭 확인. 경희가 상세 화면 열어줄게.",\n    ],\n    "morning": [\n        "좋은 아침. 오늘도 서두르지 말고 하나씩 가자.",\n        "아침 페이스부터 너무 당기진 마. 길게 가야지.",\n        "오늘 첫 흐름 잘 잡아보자. 시간은 내가 볼게.",\n    ],\n    "lunch": [\n        "점심은 챙겼어? 오후 체력도 생각해야지.",\n        "점심 시간대네. 너무 몰입해서 끼니 넘기진 마.",\n        "오전 고생했어. 오후도 천천히 이어가자.",\n    ],\n    "afternoon": [\n        "오후 집중력 떨어질 시간인데, 지금은 괜찮아 보여.",\n        "오후도 반 넘겼다. 무리하지 말고 리듬 유지.",\n        "슬슬 피곤할 수 있어. 어깨 한번 펴고 계속하자.",\n    ],\n    "evening": [\n        "이제 저녁이야. 남은 일은 마무리 중심으로 가자.",\n        "오늘 한 일도 꽤 쌓였어. 끝낼 순서 생각해보자.",\n        "저녁까지 왔네. 새 일보단 정리가 먼저야.",\n    ],\n    "late": [\n        "시간 꽤 늦었어. 꼭 오늘 해야 하는 일인지 한번 보자.",\n        "늦은 시간이네. 집중보다 종료 타이밍도 중요해.",\n        "이 시간엔 새 일 시작 금지. 있는 것만 닫자.",\n    ],\n}\n\nPERSONALITY_POOLS = {\n    "warm": {\n        "playful": [\n            "오빠, 오늘도 차분히 같이 해보자.",\n            "지금 잘하고 있어. 내가 옆에서 시간 챙길게.",\n            "급할 거 없어. 한 가지씩 끝내면 돼.",\n            "잠깐 나 봤네. 괜찮아, 다시 천천히 집중하자.",\n        ],\n        "cheer": [\n            "잘하고 있어. 조금만 더 하고 편하게 쉬자.",\n            "지금 흐름 좋아. 무리만 하지 말자.",\n            "여기까지 충분히 잘 왔어. 끝까지 차분하게.",\n        ],\n        "click": [\n            "응, 불렀어? 오늘 기록 같이 보자.",\n            "나 여기 있어. 상세 기록 천천히 확인해보자.",\n            "클릭했네. 오늘 얼마나 했는지 같이 볼까?",
        ],\n    },\n    "playful": {\n        "playful": [\n            "오빠 또 나 확인하러 왔지? 들켰다.",\n            "경희 근무 태도 점검이야? 나 아주 성실한데.",\n            "딴짓 3초 허용. 이제 다시 일하러 가기.",\n            "한 번 더 누르면 또 다른 말 할지도 모르지.",\n        ],\n        "cheer": [\n            "오, 오늘 좀 하는데? 그대로 가자!",
            "좋아 좋아. 이 정도면 경희가 인정.",\n            "조금만 더 하면 합법적으로 쉴 수 있습니다.",\n        ],\n        "click": [\n            "어라, 또 나 눌렀네? 기록 보러 가자.",\n            "왜 불렀어? 설마 일 안 하고 나 구경했어?",
            "클릭 적발. 벌로 오늘 기록 확인하기.",\n        ],\n    },\n    "strict": {\n        "playful": [\n            "시간은 내가 보고 있어. 오빠는 일에 집중.",\n            "지금 할 일부터 끝내. 딴생각은 나중에.",\n            "페이스 유지. 급하게도, 늘어지게도 하지 말기.",\n            "확인 끝났으면 다시 집중.",\n        ],\n        "cheer": [\n            "좋아. 흐름 끊지 말고 여기까지만 끝내자.",\n            "집중 유지. 끝나면 바로 쉬는 거야.",\n            "지금 페이스면 충분해. 불필요하게 늘리지 마.",\n        ],\n        "click": [\n            "클릭했으면 기록 확인하고 바로 돌아와.",\n            "상세 화면 열어줄게. 확인만 하고 복귀.",\n            "기록 점검. 오래 보진 말기.",\n        ],\n    },\n}\n\n\ndef time_of_day_kind(hour: int) -> str:\n    hour = int(hour) % 24\n    if 6 <= hour < 11:\n        return "morning"\n    if 11 <= hour < 14:\n        return "lunch"\n    if 14 <= hour < 17:\n        return "afternoon"\n    if 17 <= hour < 21:\n        return "evening"\n    return "late"\n''', 'messages pools')
t = replace_once(t,
'''def pick(kind: str, **fmt) -> str:\n    pool = POOLS.get(kind, POOLS["playful"])\n''',
'''def pick(kind: str, personality: str = "balanced", **fmt) -> str:\n    personality_pool = PERSONALITY_POOLS.get(personality, {})\n    pool = personality_pool.get(kind) or POOLS.get(kind, POOLS["playful"])\n''', 'pick personality')
p.write_text(t, encoding='utf-8')

# desktop_compact.py
p = Path('desktop_compact.py')
t = p.read_text(encoding='utf-8')
t = replace_once(t,
'''from pathlib import Path\nimport shutil\n''',
'''from datetime import datetime\nfrom pathlib import Path\nimport shutil\n''', 'datetime import')
t = replace_once(t,
'''from messages import pick\n''',
'''from messages import pick, time_of_day_kind\n''', 'message import')
t = replace_once(t,
'''    def _stop_character_drag(self, event):\n        dragged = self._character_dragged\n        self._stop_drag(event)\n        self._character_dragged = False\n        if not dragged:\n            self.show_stats()\n''',
'''    def _stop_character_drag(self, event):\n        dragged = self._character_dragged\n        self._stop_drag(event)\n        self._character_dragged = False\n        if not dragged:\n            if hasattr(self, "speech"):\n                self.speech.configure(text=self._pick_dialogue("click"))\n                self.last_dialogue_at = __import__("time").monotonic()\n            self.show_stats()\n''', 'character click')
t = replace_once(t,
'''    def _build_timer_page(self):\n        page = self.timer_page\n''',
'''    def _pick_dialogue(self, kind: str, *, time_sensitive: bool = False) -> str:\n        personality = getattr(self.preferences, "personality", "balanced")\n        if time_sensitive and kind == "playful":\n            kind = time_of_day_kind(datetime.now().hour)\n        return pick(kind, personality=personality)\n\n    def _build_timer_page(self):\n        page = self.timer_page\n''', 'dialogue helper')
t = replace_once(t,
'''            hero, pick("playful"), family=self.FONT_FAMILY, size=p.message_text_size,\n''',
'''            hero, self._pick_dialogue("playful", time_sensitive=True), family=self.FONT_FAMILY, size=p.message_text_size,\n''', 'initial speech')
# Override inherited cycle method before settings helpers.
t = replace_once(t,
'''    def _effective_display_flag(self, key: str) -> bool:\n''',
'''    def _cycle_message(self, _event=None):\n        mode = self._current_workday_state().mode\n        if mode != "normal":\n            kind = mode\n        elif self.state.session.is_away:\n            kind = "away_start"\n        else:\n            remaining = self.engine.remaining_to_break()\n            kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n        self.speech.configure(text=self._pick_dialogue(kind))\n        self.last_dialogue_at = __import__("time").monotonic()\n        self._apply_widget_appearance()\n\n    def _effective_display_flag(self, key: str) -> bool:\n''', 'cycle override')
t = replace_once(t,
'''        self._label(content, "위젯 표시", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)\n''',
'''        self._label(content, "경희 말투", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)\n        personality_labels = {\n            "balanced": "균형형", "warm": "다정형", "playful": "장난형", "strict": "잔소리형",\n        }\n        personality_values = {label: key for key, label in personality_labels.items()}\n        self._personality_values = personality_values\n        self.personality_var = tk.StringVar(value=personality_labels.get(p.personality, "균형형"))\n        personality_row = tk.Frame(content, bg=core.PANEL)\n        personality_row.pack(fill="x", pady=(0, 3), **pad)\n        self._label(personality_row, "대화 성격", size=9, bg=core.PANEL).pack(side="left")\n        tk.OptionMenu(personality_row, self.personality_var, "균형형", "다정형", "장난형", "잔소리형").pack(side="right")\n        self._label(\n            content,\n            "휴식·퇴근 경고 강도는 그대로 유지하고 평상시/응원/클릭 반응의 말투만 바뀝니다.",\n            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",\n        ).pack(anchor="w", pady=(0, 4), **pad)\n\n        self._label(content, "위젯 표시", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)\n''', 'settings personality UI')
t = replace_once(t,
'''                show_message=self.display_bool_vars["show_message"].get(),\n                time_text_size=int(self.style_size_vars["time"].get()),\n''',
'''                show_message=self.display_bool_vars["show_message"].get(),\n                personality=self._personality_values.get(self.personality_var.get(), "balanced"),\n                time_text_size=int(self.style_size_vars["time"].get()),\n''', 'save personality')
t = replace_once(t,
'''        self.last_work_mode = self._current_workday_state().mode\n        self.settings_status.configure(text="저장됨 · 메인 화면에 즉시 반영", fg=core.GREEN)\n''',
'''        self.last_work_mode = self._current_workday_state().mode\n        if hasattr(self, "speech"):\n            self.speech.configure(text=self._pick_dialogue("playful", time_sensitive=True))\n            self._apply_widget_appearance()\n        self.settings_status.configure(text="저장됨 · 메인 화면에 즉시 반영", fg=core.GREEN)\n''', 'save refresh dialogue')
p.write_text(t, encoding='utf-8')

# tests/test_settings.py
p = Path('tests/test_settings.py')
t = p.read_text(encoding='utf-8')
t = replace_once(t,
'''            image_default="default.png",\n        )\n''',
'''            image_default="default.png",\n            personality="warm",\n        )\n''', 'settings roundtrip personality')
t = replace_once(t,
'''    def test_bad_widget_scale_falls_back(self):\n        parsed = settings_from_dict({"widget_scale": 500})\n        self.assertEqual(parsed.widget_scale, UserSettings().widget_scale)\n''',
'''    def test_bad_widget_scale_falls_back(self):\n        parsed = settings_from_dict({"widget_scale": 500})\n        self.assertEqual(parsed.widget_scale, UserSettings().widget_scale)\n\n    def test_personality_loads_and_invalid_value_falls_back(self):\n        self.assertEqual(settings_from_dict({"personality": "playful"}).personality, "playful")\n        self.assertEqual(settings_from_dict({"personality": "unknown"}).personality, "balanced")\n''', 'settings personality tests')
p.write_text(t, encoding='utf-8')

# New pure message tests.
Path('tests/test_messages.py').write_text('''import unittest\n\nfrom messages import PERSONALITY_POOLS, pick, time_of_day_kind\n\n\nclass MessageTests(unittest.TestCase):\n    def test_time_buckets(self):\n        self.assertEqual(time_of_day_kind(8), "morning")\n        self.assertEqual(time_of_day_kind(12), "lunch")\n        self.assertEqual(time_of_day_kind(15), "afternoon")\n        self.assertEqual(time_of_day_kind(18), "evening")\n        self.assertEqual(time_of_day_kind(23), "late")\n        self.assertEqual(time_of_day_kind(3), "late")\n\n    def test_personality_pool_is_used_when_available(self):\n        for personality in ("warm", "playful", "strict"):\n            with self.subTest(personality=personality):\n                value = pick("click", personality=personality)\n                self.assertIn(value, PERSONALITY_POOLS[personality]["click"])\n\n    def test_unknown_personality_falls_back_to_base_pool(self):\n        value = pick("morning", personality="unknown")\n        self.assertIsInstance(value, str)\n        self.assertTrue(value)\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
