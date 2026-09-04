from __future__ import annotations
import random

POOLS = {
    "playful": [
        "오빠~ 오늘도 내가 시간 감시한다?",
        "흠, 오늘 제법 성실한데?",
        "경희 비서 근무 중. 시간은 나한테 맡겨.",
        "오빠, 지금 페이스 괜찮아. 그대로 가자.",
        "다음 휴식까지 내가 세고 있어.",
        "시간 신경 쓰지 말고 하던 거 해.",
        "집중하는 얼굴이네. 방해는 조금만 할게.",
        "지금 흐름 좋다. 내가 옆에서 조용히 지켜볼게.",
        "한 번 눌렀다고 바로 다른 말 해주는 거 봐.",
        "시간 확인하러 왔어? 아직 내가 잘 세고 있어.",
        "오늘 할 일 하나씩 지워보자.",
        "잠깐 나 본 거지? 확인했으면 다시 집중.",
        "급하게 하지 마. 꾸준히 가는 게 더 빨라.",
        "경희는 정상 근무 중. 오빠도 계속해.",
        "딴생각 났어? 그럼 딱 여기까지만 보고 돌아가기.",
        "좋아, 지금 리듬 그대로 유지해보자.",
        "말 걸어도 돼. 대신 하던 일은 잊지 말기.",
        "오늘도 기록은 솔직하게 남겨둘게.",
    ],
    "cheer": [
        "오빠, 파이팅! 지금 흐름 좋아!",
        "좋아! 이대로 조금만 더 가자!",
        "오빠, 잘하고 있어! 내가 응원한다!",
        "파이팅! 다음 휴식까지 얼마 안 남았어.",
        "여기까지 잘 왔어. 마무리만 차분하게 하자.",
        "조금만 더 집중하면 기분 좋게 쉴 수 있어.",
        "흐름 안 끊기게 내가 시간 보고 있을게.",
        "지금 속도면 충분해. 무리해서 당기진 마.",
        "좋아, 마지막 구간이야. 어깨 힘은 빼고.",
        "거의 다 왔어. 끝나면 꼭 일어나기.",
    ],
    "nag": [
        "흥. 몇 번을 말해야 쉬는 거야?",
        "오빠 또 안 쉬고 계속하려고?",
        "이번에는 내 말 좀 들어.",
        "또 5분 더? 그 5분이 계속 늘어나잖아.",
    ],
    "worry": [
        "오빠, 좀 오래 앉아 있었어. 괜찮아?",
        "목이랑 어깨 한번 풀자.",
        "눈 피곤하지 않아? 잠깐 쉬어도 돼.",
        "자세 한번만 고쳐 앉자. 허리 너무 굳겠다.",
        "물은 마셨어? 한 모금 정도는 괜찮잖아.",
        "집중도 좋지만 몸이 먼저야. 잠깐 움직이자.",
        "눈 한번 멀리 보고 와. 내가 기다릴게.",
        "손목이랑 손가락도 가볍게 풀어줘.",
    ],
    "praise": [
        "엄지 척. 오늘 정말 잘했어.",
        "오빠, 오늘 기록 꽤 좋다.",
        "오늘 집중력 인정.",
    ],
    "return": [
        "{away} 쉬고 왔네. 다시 시작할게.",
        "복귀 확인. {away}만큼은 자리비움으로 기록했어.",
        "오빠 왔네. {away} 쉬었어.",
    ],
    "away_start": [
        "다녀와. 그동안 시간은 빼둘게.",
        "자리비움 시작. 편하게 다녀와.",
        "천천히 다녀와. 돌아오면 다시 이어줄게.",
        "좋아, 잠깐 쉬는 걸로 기록해둘게.",
        "자리 비운 시간은 내가 정확히 챙겨둘게.",
    ],
    "break": [
        "오빠, 딱 한 시간 썼어. 이제 5분만 쉬자.",
        "한 시간 완료. 눈이랑 어깨 쉬는 시간.",
    ],
    "snooze1": [
        "알겠어. 딱 5분만 더야.",
        "5분만 더. 진짜 5분이다?",
    ],
    "snooze2": [
        "또 5분? 슬슬 토라질 건데.",
        "오빠, 두 번째야. 이번엔 진짜 쉬어.",
    ],
    "stats": [
        "오늘 기록 같이 볼까?",
        "오빠, 오늘 페이스 한번 확인해보자.",
    ],
    "wind_down": [
        "슬슬 오늘 할 일 정리할 시간이야.",
        "이제 새 일 벌이기보다 하던 것부터 마무리하자.",
        "마무리 예고 시간이야. 오늘 남은 건 정리 모드로 가자.",
    ],
    "leave": [
        "이제 퇴근 모드로 갈게. 하던 것만 마무리하자.",
        "오빠, 이제 마무리하고 갈 준비하자.",
        "퇴근 모드 시작. 새 일은 내일의 오빠한테 넘기자.",
    ],
    "strong_leave": [
        "이제 퇴근할 시간이야. 새 일 벌이지 말고 정리하자.",
        "적극 퇴근 권고 시간이야. 오늘 할 만큼 했어. 이제 닫자.",
        "오빠, 이제 정말 정리하고 가자.",
    ],
    "late_leave": [
        "야근 알림 시간이 지났어. 오늘 일은 여기서 닫자.",
        "설마 또 야근하려고? 이제 컴퓨터 정리하자.",
        "오빠, 오늘은 여기까지. 내일 해도 돼.",
    ],
    "hard_stop": [
        "오늘 실사용 9시간이야. 이제는 진짜 끝내자.",
        "9시간 채웠어. 더 하는 건 내가 반대야. 이제 가자.",
        "오늘 충분히 했어. 여기서 업무 종료.",
    ],
    "click": [
        "응, 나 눌렀어? 기록 보러 가자.",
        "불렀어? 오늘 기록 같이 보자.",
        "왜, 나 보고 싶었어? 일단 기록부터 확인.",
        "클릭 확인. 경희가 상세 화면 열어줄게.",
    ],
    "morning": [
        "좋은 아침. 오늘도 서두르지 말고 하나씩 가자.",
        "아침 페이스부터 너무 당기진 마. 길게 가야지.",
        "오늘 첫 흐름 잘 잡아보자. 시간은 내가 볼게.",
    ],
    "lunch": [
        "점심은 챙겼어? 오후 체력도 생각해야지.",
        "점심 시간대네. 너무 몰입해서 끼니 넘기진 마.",
        "오전 고생했어. 오후도 천천히 이어가자.",
    ],
    "afternoon": [
        "오후 집중력 떨어질 시간인데, 지금은 괜찮아 보여.",
        "오후도 반 넘겼다. 무리하지 말고 리듬 유지.",
        "슬슬 피곤할 수 있어. 어깨 한번 펴고 계속하자.",
    ],
    "evening": [
        "이제 저녁이야. 남은 일은 마무리 중심으로 가자.",
        "오늘 한 일도 꽤 쌓였어. 끝낼 순서 생각해보자.",
        "저녁까지 왔네. 새 일보단 정리가 먼저야.",
    ],
    "late": [
        "시간 꽤 늦었어. 꼭 오늘 해야 하는 일인지 한번 보자.",
        "늦은 시간이네. 집중보다 종료 타이밍도 중요해.",
        "이 시간엔 새 일 시작 금지. 있는 것만 닫자.",
    ],
}

RARE_POOLS = {
    "balanced": [
        "잠깐만. 오늘 내가 꽤 열심히 챙겨주고 있는 거 알지?",
        "이 말은 자주 안 해주는데… 오늘 페이스, 꽤 마음에 들어.",
        "경희 비밀 점검 결과: 지금은 딴짓 판정 아님. 계속해도 됨.",
        "가끔은 내가 먼저 말 걸어도 되잖아. 잘하고 있어.",
    ],
    "warm": [
        "이건 가끔만 말할게. 오늘도 같이 있어서 좋네.",
        "조용히 응원하고 있었어. 생각보다 훨씬 잘하고 있어.",
        "오늘은 특별 칭찬 한 번. 무리하지 않고 여기까지 온 거 잘했어.",
    ],
    "playful": [
        "희귀 대사 당첨. 축하합니다. 상품은 10초간 경희 구경권입니다.",
        "쉿, 이건 자주 안 나오는 대사야. 캡처할 거면 지금 해.",
        "이스터에그 발견. 근데 찾았다고 일 안 해도 되는 건 아님.",
        "경희 숨겨둔 대사 발견했네. 운 좋은데?",
    ],
    "strict": [
        "특별 점검 결과: 오늘은 잔소리 보류. 지금처럼만 해.",
        "이 말 자주 안 한다. 지금 페이스는 합격.",
        "예외적으로 칭찬한다. 흐름 좋으니까 괜히 깨지 마.",
    ],
}

RARE_CHANCE = 0.04
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

PERSONALITY_POOLS = {
    "warm": {
        "playful": [
            "오빠, 오늘도 차분히 같이 해보자.",
            "지금 잘하고 있어. 내가 옆에서 시간 챙길게.",
            "급할 거 없어. 한 가지씩 끝내면 돼.",
            "잠깐 나 봤네. 괜찮아, 다시 천천히 집중하자.",
        ],
        "cheer": [
            "잘하고 있어. 조금만 더 하고 편하게 쉬자.",
            "지금 흐름 좋아. 무리만 하지 말자.",
            "여기까지 충분히 잘 왔어. 끝까지 차분하게.",
        ],
        "click": [
            "응, 불렀어? 오늘 기록 같이 보자.",
            "나 여기 있어. 상세 기록 천천히 확인해보자.",
            "클릭했네. 오늘 얼마나 했는지 같이 볼까?",
        ],
    },
    "playful": {
        "playful": [
            "오빠 또 나 확인하러 왔지? 들켰다.",
            "경희 근무 태도 점검이야? 나 아주 성실한데.",
            "딴짓 3초 허용. 이제 다시 일하러 가기.",
            "한 번 더 누르면 또 다른 말 할지도 모르지.",
        ],
        "cheer": [
            "오, 오늘 좀 하는데? 그대로 가자!",
            "좋아 좋아. 이 정도면 경희가 인정.",
            "조금만 더 하면 합법적으로 쉴 수 있습니다.",
        ],
        "click": [
            "어라, 또 나 눌렀네? 기록 보러 가자.",
            "왜 불렀어? 설마 일 안 하고 나 구경했어?",
            "클릭 적발. 벌로 오늘 기록 확인하기.",
        ],
    },
    "strict": {
        "playful": [
            "시간은 내가 보고 있어. 오빠는 일에 집중.",
            "지금 할 일부터 끝내. 딴생각은 나중에.",
            "페이스 유지. 급하게도, 늘어지게도 하지 말기.",
            "확인 끝났으면 다시 집중.",
        ],
        "cheer": [
            "좋아. 흐름 끊지 말고 여기까지만 끝내자.",
            "집중 유지. 끝나면 바로 쉬는 거야.",
            "지금 페이스면 충분해. 불필요하게 늘리지 마.",
        ],
        "click": [
            "클릭했으면 기록 확인하고 바로 돌아와.",
            "상세 화면 열어줄게. 확인만 하고 복귀.",
            "기록 점검. 오래 보진 말기.",
        ],
    },
}


def habit_dialogue_kind(
    *,
    away_count: int,
    longest_continuous: float,
    continuous_seconds: float,
) -> str | None:
    """Choose a lightweight habit reaction from already-recorded timer stats."""
    continuous = max(0.0, float(continuous_seconds))
    longest = max(0.0, float(longest_continuous))
    breaks = max(0, int(away_count))
    if continuous >= 75 * 60:
        return "nag"
    if breaks >= 3 and longest <= 75 * 60:
        return "praise"
    if continuous >= 50 * 60:
        return "worry"
    return None


def daily_temperament(date_key: str) -> str:
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


def time_of_day_kind(hour: int) -> str:
    hour = int(hour) % 24
    if 6 <= hour < 11:
        return "morning"
    if 11 <= hour < 14:
        return "lunch"
    if 14 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 21:
        return "evening"
    return "late"

_recent = []
_rare_gap = RARE_MIN_GAP
_recent_rare = []


def pick(kind: str, personality: str = "balanced", **fmt) -> str:
    personality_pool = PERSONALITY_POOLS.get(personality, {})
    pool = personality_pool.get(kind) or POOLS.get(kind, POOLS["playful"])
    candidates = [m for m in pool if m not in _recent[-10:]] or pool
    msg = random.choice(candidates)
    _recent.append(msg)
    if len(_recent) > 40:
        del _recent[:-25]
    try:
        return msg.format(**fmt)
    except Exception:
        return msg


def custom_dialogue_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def maybe_pick_custom(value: str, *, chance: float = 0.25, roll: float | None = None) -> str | None:
    lines = custom_dialogue_lines(value)
    if not lines:
        return None
    sample = random.random() if roll is None else float(roll)
    if sample >= max(0.0, min(1.0, float(chance))):
        return None
    candidates = [line for line in lines if line not in _recent[-10:]] or lines
    msg = random.choice(candidates)
    _recent.append(msg)
    if len(_recent) > 40:
        del _recent[:-25]
    return msg


def maybe_pick_rare(
    personality: str = "balanced",
    *,
    chance: float = RARE_CHANCE,
    roll: float | None = None,
) -> str | None:
    """Return a rare line only after enough ordinary selections have elapsed.

    This helper is intentionally separate from pick(): safety/workflow dialogue can
    keep calling pick() and will never be replaced by an easter egg.
    """
    global _rare_gap
    _rare_gap += 1
    if _rare_gap < RARE_MIN_GAP:
        return None
    value = random.random() if roll is None else float(roll)
    if value >= max(0.0, min(1.0, float(chance))):
        return None
    pool = RARE_POOLS.get(personality) or RARE_POOLS["balanced"]
    candidates = [m for m in pool if m not in _recent_rare[-2:]] or pool
    msg = random.choice(candidates)
    _recent_rare.append(msg)
    if len(_recent_rare) > 8:
        del _recent_rare[:-4]
    _rare_gap = 0
    return msg


def _reset_rare_state_for_tests(gap: int = RARE_MIN_GAP) -> None:
    global _rare_gap
    _rare_gap = int(gap)
    _recent_rare.clear()
