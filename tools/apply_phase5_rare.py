from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f'{label}: expected 1 match, found {count}')
    return text.replace(old, new, 1)


messages = Path('messages.py')
text = messages.read_text(encoding='utf-8')

anchor = '''PERSONALITY_POOLS = {\n'''
rare = '''RARE_POOLS = {\n    "balanced": [\n        "잠깐만. 오늘 내가 꽤 열심히 챙겨주고 있는 거 알지?",\n        "이 말은 자주 안 해주는데… 오늘 페이스, 꽤 마음에 들어.",\n        "경희 비밀 점검 결과: 지금은 딴짓 판정 아님. 계속해도 됨.",\n        "가끔은 내가 먼저 말 걸어도 되잖아. 잘하고 있어.",\n    ],\n    "warm": [\n        "이건 가끔만 말할게. 오늘도 같이 있어서 좋네.",\n        "조용히 응원하고 있었어. 생각보다 훨씬 잘하고 있어.",\n        "오늘은 특별 칭찬 한 번. 무리하지 않고 여기까지 온 거 잘했어.",\n    ],\n    "playful": [\n        "희귀 대사 당첨. 축하합니다. 상품은 10초간 경희 구경권입니다.",\n        "쉿, 이건 자주 안 나오는 대사야. 캡처할 거면 지금 해.",\n        "이스터에그 발견. 근데 찾았다고 일 안 해도 되는 건 아님.",\n        "경희 숨겨둔 대사 발견했네. 운 좋은데?",
    ],\n    "strict": [\n        "특별 점검 결과: 오늘은 잔소리 보류. 지금처럼만 해.",\n        "이 말 자주 안 한다. 지금 페이스는 합격.",\n        "예외적으로 칭찬한다. 흐름 좋으니까 괜히 깨지 마.",\n    ],\n}\n\nRARE_CHANCE = 0.04\nRARE_MIN_GAP = 12\n\n'''
text = replace_once(text, anchor, rare + anchor, 'insert rare pools')

old_tail = '''_recent = []\n\n\ndef pick(kind: str, personality: str = "balanced", **fmt) -> str:\n    personality_pool = PERSONALITY_POOLS.get(personality, {})\n    pool = personality_pool.get(kind) or POOLS.get(kind, POOLS["playful"])\n    candidates = [m for m in pool if m not in _recent[-10:]] or pool\n    msg = random.choice(candidates)\n    _recent.append(msg)\n    if len(_recent) > 40:\n        del _recent[:-25]\n    try:\n        return msg.format(**fmt)\n    except Exception:\n        return msg\n'''
new_tail = '''_recent = []\n_rare_gap = RARE_MIN_GAP\n_recent_rare = []\n\n\ndef pick(kind: str, personality: str = "balanced", **fmt) -> str:\n    personality_pool = PERSONALITY_POOLS.get(personality, {})\n    pool = personality_pool.get(kind) or POOLS.get(kind, POOLS["playful"])\n    candidates = [m for m in pool if m not in _recent[-10:]] or pool\n    msg = random.choice(candidates)\n    _recent.append(msg)\n    if len(_recent) > 40:\n        del _recent[:-25]\n    try:\n        return msg.format(**fmt)\n    except Exception:\n        return msg\n\n\ndef maybe_pick_rare(\n    personality: str = "balanced",\n    *,\n    chance: float = RARE_CHANCE,\n    roll: float | None = None,\n) -> str | None:\n    \"\"\"Return a rare line only after enough ordinary selections have elapsed.\n\n    This helper is intentionally separate from pick(): safety/workflow dialogue can\n    keep calling pick() and will never be replaced by an easter egg.\n    \"\"\"\n    global _rare_gap\n    _rare_gap += 1\n    if _rare_gap < RARE_MIN_GAP:\n        return None\n    value = random.random() if roll is None else float(roll)\n    if value >= max(0.0, min(1.0, float(chance))):\n        return None\n    pool = RARE_POOLS.get(personality) or RARE_POOLS["balanced"]\n    candidates = [m for m in pool if m not in _recent_rare[-2:]] or pool\n    msg = random.choice(candidates)\n    _recent_rare.append(msg)\n    if len(_recent_rare) > 8:\n        del _recent_rare[:-4]\n    _rare_gap = 0\n    return msg\n\n\ndef _reset_rare_state_for_tests(gap: int = RARE_MIN_GAP) -> None:\n    global _rare_gap\n    _rare_gap = int(gap)\n    _recent_rare.clear()\n'''
text = replace_once(text, old_tail, new_tail, 'replace messages tail')
messages.write_text(text, encoding='utf-8')


desktop = Path('desktop_compact.py')
d = desktop.read_text(encoding='utf-8')
d = replace_once(
    d,
    'from messages import pick, time_of_day_kind\n',
    'from messages import maybe_pick_rare, pick, time_of_day_kind\n',
    'desktop import',
)
old = '''        else:\n            remaining = self.engine.remaining_to_break()\n            kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n        self.speech.configure(text=self._pick_dialogue(kind))\n        self.last_dialogue_at = __import__("time").monotonic()\n'''
new = '''        else:\n            remaining = self.engine.remaining_to_break()\n            kind = "cheer" if remaining <= 15 * 60 else time_of_day_kind(datetime.now().hour)\n            rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))\n            if rare:\n                self.speech.configure(text=rare)\n                self.last_dialogue_at = __import__("time").monotonic()\n                self._apply_widget_appearance()\n                return\n        self.speech.configure(text=self._pick_dialogue(kind))\n        self.last_dialogue_at = __import__("time").monotonic()\n'''
d = replace_once(d, old, new, 'cycle rare')
desktop.write_text(d, encoding='utf-8')


test = Path('tests/test_messages.py')
test.write_text('''import unittest\n\nfrom messages import (\n    RARE_MIN_GAP,\n    RARE_POOLS,\n    _reset_rare_state_for_tests,\n    maybe_pick_rare,\n    time_of_day_kind,\n)\n\n\nclass MessageBehaviorTests(unittest.TestCase):\n    def tearDown(self):\n        _reset_rare_state_for_tests()\n\n    def test_time_of_day_boundaries(self):\n        self.assertEqual(time_of_day_kind(6), "morning")\n        self.assertEqual(time_of_day_kind(11), "lunch")\n        self.assertEqual(time_of_day_kind(14), "afternoon")\n        self.assertEqual(time_of_day_kind(17), "evening")\n        self.assertEqual(time_of_day_kind(21), "late")\n\n    def test_rare_dialogue_respects_minimum_gap(self):\n        _reset_rare_state_for_tests(0)\n        for _ in range(RARE_MIN_GAP - 1):\n            self.assertIsNone(maybe_pick_rare("balanced", chance=1.0, roll=0.0))\n        self.assertIn(maybe_pick_rare("balanced", chance=1.0, roll=0.0), RARE_POOLS["balanced"])\n\n    def test_rare_dialogue_respects_chance(self):\n        _reset_rare_state_for_tests()\n        self.assertIsNone(maybe_pick_rare("balanced", chance=0.04, roll=0.5))\n        self.assertIn(maybe_pick_rare("balanced", chance=0.04, roll=0.0), RARE_POOLS["balanced"])\n\n    def test_unknown_personality_falls_back_to_balanced(self):\n        _reset_rare_state_for_tests()\n        self.assertIn(maybe_pick_rare("unknown", chance=1.0, roll=0.0), RARE_POOLS["balanced"])\n\n\nif __name__ == "__main__":\n    unittest.main()\n''', encoding='utf-8')
