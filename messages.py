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
    ],
    "cheer": [
        "오빠, 파이팅! 지금 흐름 좋아!",
        "좋아! 이대로 조금만 더 가자!",
        "오빠, 잘하고 있어! 내가 응원한다!",
        "파이팅! 다음 휴식까지 얼마 안 남았어.",
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
}

_recent = []

def pick(kind: str, **fmt) -> str:
    pool = POOLS.get(kind, POOLS["playful"])
    candidates = [m for m in pool if m not in _recent[-10:]] or pool
    msg = random.choice(candidates)
    _recent.append(msg)
    if len(_recent) > 40:
        del _recent[:-25]
    try:
        return msg.format(**fmt)
    except Exception:
        return msg
