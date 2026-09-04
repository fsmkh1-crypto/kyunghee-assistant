from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{label}: expected exactly one match, found {text.count(old)}")
    return text.replace(old, new, 1)


messages_path = ROOT / "messages.py"
messages = messages_path.read_text(encoding="utf-8")

marker = "RARE_CHANCE = 0.04\nRARE_MIN_GAP = 12\n\n"
insert = '''RARE_CHANCE = 0.04
RARE_MIN_GAP = 12

DAILY_TEMPERAMENT_CHANCE = 0.18
DAILY_TEMPERAMENT_POOLS = {
    "calm": [
        "오늘 경희는 좀 차분한 날이야. 서두르지 말고 하나씩 하자.",
        "오늘은 조용히 옆에서 시간만 잘 챙겨줄게.",
        "오늘 분위기는 차분하게. 속도보다 흐름 유지가 먼저야.",
    ],
    "bright": [
        "오늘 경희는 기분이 좀 좋은가 봐. 오빠도 페이스 올려볼까?",
        "오늘은 왠지 잘 풀릴 것 같은데? 하나씩 끝내보자.",
        "오늘 경희 컨디션 좋음. 응원 서비스 조금 더 들어갑니다.",
    ],
    "focused": [
        "오늘은 집중 모드야. 할 일 하나 잡고 깔끔하게 끝내자.",
        "오늘 경희는 업무 모드가 강한 날. 딴짓은 짧게만.",
        "오늘은 흐름 끊지 말고 정리정돈하듯 하나씩 처리하자.",
    ],
}

'''
messages = replace_once(messages, marker, insert, "daily pool insertion")

func_marker = "def time_of_day_kind(hour: int) -> str:\n"
func_insert = '''def daily_temperament(date_key: str) -> str:
    """Return a stable lightweight temperament for one calendar date."""
    key = str(date_key or "")
    total = sum((index + 1) * ord(char) for index, char in enumerate(key))
    names = tuple(DAILY_TEMPERAMENT_POOLS)
    return names[total % len(names)]


def maybe_pick_daily_temperament(
    date_key: str,
    *,
    chance: float = DAILY_TEMPERAMENT_CHANCE,
    roll: float | None = None,
) -> str | None:
    if roll is None:
        roll = random.random()
    if float(roll) >= float(chance):
        return None
    mood = daily_temperament(date_key)
    return random.choice(DAILY_TEMPERAMENT_POOLS[mood])


'''
messages = replace_once(messages, func_marker, func_insert + func_marker, "daily helper insertion")
messages_path.write_text(messages, encoding="utf-8")

compact_path = ROOT / "desktop_compact.py"
compact = compact_path.read_text(encoding="utf-8")
old_import = "from messages import habit_dialogue_kind, maybe_pick_custom, maybe_pick_rare, pick, time_of_day_kind\n"
new_import = "from messages import habit_dialogue_kind, maybe_pick_custom, maybe_pick_daily_temperament, maybe_pick_rare, pick, time_of_day_kind\n"
compact = replace_once(compact, old_import, new_import, "desktop import")
old_block = '''                rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))
                if rare:
                    self.speech.configure(text=rare)
                    self.last_dialogue_at = __import__("time").monotonic()
                    self._apply_widget_appearance()
                    return
'''
new_block = '''                rare = maybe_pick_rare(getattr(self.preferences, "personality", "balanced"))
                if rare:
                    self.speech.configure(text=rare)
                    self.last_dialogue_at = __import__("time").monotonic()
                    self._apply_widget_appearance()
                    return
                daily = maybe_pick_daily_temperament(datetime.now().date().isoformat())
                if daily:
                    self.speech.configure(text=daily)
                    self.last_dialogue_at = __import__("time").monotonic()
                    self._apply_widget_appearance()
                    return
'''
compact = replace_once(compact, old_block, new_block, "desktop daily hook")
compact_path.write_text(compact, encoding="utf-8")

test_path = ROOT / "tests" / "test_messages.py"
test = test_path.read_text(encoding="utf-8")
old_test_import = '''    RARE_MIN_GAP,
    RARE_POOLS,
    custom_dialogue_lines,
'''
new_test_import = '''    DAILY_TEMPERAMENT_POOLS,
    RARE_MIN_GAP,
    RARE_POOLS,
    custom_dialogue_lines,
    daily_temperament,
'''
test = replace_once(test, old_test_import, new_test_import, "test import 1")
old_test_import2 = '''    maybe_pick_custom,
    _reset_rare_state_for_tests,
'''
new_test_import2 = '''    maybe_pick_custom,
    maybe_pick_daily_temperament,
    _reset_rare_state_for_tests,
'''
test = replace_once(test, old_test_import2, new_test_import2, "test import 2")
anchor = '''    def test_rare_dialogue_respects_minimum_gap(self):
'''
new_tests = '''    def test_daily_temperament_is_stable_for_same_date(self):
        first = daily_temperament("2026-09-04")
        self.assertEqual(first, daily_temperament("2026-09-04"))
        self.assertIn(first, DAILY_TEMPERAMENT_POOLS)

    def test_daily_temperament_respects_chance(self):
        self.assertIsNone(maybe_pick_daily_temperament("2026-09-04", chance=0.18, roll=0.9))
        selected = maybe_pick_daily_temperament("2026-09-04", chance=1.0, roll=0.0)
        mood = daily_temperament("2026-09-04")
        self.assertIn(selected, DAILY_TEMPERAMENT_POOLS[mood])

'''
test = replace_once(test, anchor, new_tests + anchor, "daily tests")
test_path.write_text(test, encoding="utf-8")

print("Phase 5 daily temperament applied")
