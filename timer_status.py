"""Read-only Korean timer queries and deterministic formatting of fresh values.

The caller supplies an authoritative snapshot from the existing timer loop and
a monotonic current-run elapsed value. This module never advances the engine,
reads files, calls an API, changes settings, or samples a clock itself.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math
import re
import unicodedata

MAX_QUERY_LENGTH = 400
QUERY_KINDS = frozenset({"runtime", "active", "continuous", "away", "clock", "all"})
_QUOTES = frozenset("'\"“”‘’「」『』«»") | {chr(96)}
_NON_TIMER_TOPIC = re.compile(
    r"시간\s*(?:관리|여행|표|대|복잡도|개념)|타이머\s*(?:만드는|구현|코드|추천|설치)|"
    r"방법|요령|노하우|공부법|설명해|정의|번역|영어로|뜻이|뜻을|"
    r"(?:회의|약속|영화|버스|기차|비행|수업|배송|출근|퇴근)\s*(?:시간|몇\s*시|시각)|"
    r"(?:돈|금액|가격|비용|예산|지출)(?:\s|을|이|은|얼마|썼|써|쓴)"
)
_NOT_A_CURRENT_QUERY = re.compile(
    r"예를\s*들|예시|가정|만약|라고\s*(?:말|물)|라는\s*(?:말|문장)|"
    r"알려\s*주지|보여\s*주지|안\s*(?:알려|보여)|말아|말고|하지\s*마|"
    r"나중에|예약|알림\s*설정|[0-9]+\s*(?:초|분|시간)\s*(?:뒤|후)|시간\s*되면|"
    r"바꿔|변경해|설정해|초기화해|리셋해|멈춰|중지해|종료해"
)
_READ_CUE = re.compile(
    r"얼마|몇\s*(?:초|분|시간|시)|알려|보여|체크|확인|경과|지났|"
    r"돌아(?:갔|가|간)|흘렀|어때|안\s*(?:늘|가|올라)|멈(?:췄|춘)|"
    r"그대로|0\s*(?:초|분|시간|이|으로)"
)
_DURATION_CUE = re.compile(r"얼마|몇\s*(?:초|분|시간)|경과|지났|돌아(?:갔|가|간)|흘렀")
_TIME_WORD = re.compile(r"시간|시각|타이머|경과|몇\s*(?:초|분|시)|[0-9]+\s*(?:초|분|시간)")
_RUNTIME = re.compile(r"앱|프로그램|실행|기동|구동|켠|켜\s*(?:진|져|둔|놓|고)|시작한\s*지")
_CONTINUOUS = re.compile(r"연속|끊김\s*없이|쉬지\s*않고")
_AWAY = re.compile(r"자리\s*비움|자리\s*비운|자리\s*비웠|휴식|쉬었|쉬고|쉬는|쉰")
_ACTIVE = re.compile(r"사용|활동|업무|작업|근무|일했|일한|일하고|썼|쓰고|쓴")
_CLOCK = re.compile(r"몇\s*시(?:야|지|니|냐|고|예요|에요|인가|인지|(?=$))|(?:지금|현재)\s*(?:시간|시각)")
_BARE_METRIC = re.compile(
    r"(?:(?:오늘|현재|지금|총|누적|실제)\s*)*"
    r"(?:시간|시각|타이머(?:\s*(?:시간|상태))?|"
    r"(?:(?:연속\s*)?사용|실제\s*사용|사용한|일한|작업한|근무한|쉰|쉬는|업무|작업|근무|활동|휴식|자리\s*비움|"
    r"앱\s*실행|실행)\s*(?:시간|경과|상태))(?:은|는|이|가)?\s*\Z"
)
_GENERIC_DURATION_QUERY = re.compile(
    r"(?:(?:지금|현재|오늘|벌써|이제|나)\s*)?"
    r"(?:몇\s*(?:초|분|시간)\s*(?:째|이나|정도|동안|이야|야|됐|지났).*|"
    r"얼마나\s*(?:됐|지났|돌아갔|흘렀|했(?:어|냐|니|지|어요)).*)\Z"
)
_GENERIC_TIME_QUERY = re.compile(
    r"(?:(?:지금|현재|오늘|이제)\s*)?시간(?:을|를|이|은)?\s*(?:좀\s*)?"
    r"(?:알려|보여|체크|확인|왜\s*안\s*(?:늘|가|올라|돌아)|안\s*(?:늘|가|올라|돌아)|"
    r"얼마나\s*(?:됐|지났|흘렀|돌아)).*\Z"
)


def _query_text(value: object) -> str:
    if type(value) is not str or not 0 < len(value) <= MAX_QUERY_LENGTH:
        return ""
    if any(char in _QUOTES for char in value) or any(
        unicodedata.category(char) == "Cc" and not char.isspace() for char in value
    ):
        return ""
    text = " ".join(unicodedata.normalize("NFKC", value).lower().split()).rstrip(".!?~ ")
    text = re.sub(r"^(?:승아야|경희야)[,\s]*", "", text)
    return re.sub(r"^(?:(?:야|저기요|저기|혹시)[,\s]+){1,3}", "", text)


def classify_timer_query(user_text: str) -> str | None:
    """Recognize current factual time questions without fixed sentence grammar.

    General timer/duration questions return all. App runtime is this process's
    elapsed time, never a substitute for today's active or continuous use.
    """
    text = _query_text(user_text)
    if not text or _NON_TIMER_TOPIC.search(text) or _NOT_A_CURRENT_QUERY.search(text):
        return None
    bare = bool(_BARE_METRIC.fullmatch(text))
    read = bool(_READ_CUE.search(text))
    duration = bool(_DURATION_CUE.search(text))
    time_word = bool(_TIME_WORD.search(text))
    if not (bare or read):
        return None
    # A named counter needs a time/duration cue. Ordinary comments such as
    # "오늘 작업 어때" and "휴식 보여줘" remain normal conversation.
    metric = bare or time_word or duration
    continuous = bool(_CONTINUOUS.search(text)) and metric
    away = bool(_AWAY.search(text)) and metric
    runtime = bool(_RUNTIME.search(text)) and metric
    active = bool(_ACTIVE.search(text)) and metric
    clock = bool(_CLOCK.search(text)) and (bare or read)
    if clock and (continuous or away or runtime or active):
        return "all"
    if continuous and away:
        return "all"
    if continuous:
        return "continuous"
    if away:
        return "away"
    if runtime:
        return "runtime"
    if active:
        return "active"
    if clock or bare and text in {"현재 시간", "현재시간", "현재 시각", "현재시각", "지금 시간", "지금시간", "지금 시각", "지금시각", "시각"}:
        return "clock"
    if bare or "타이머" in text or _GENERIC_DURATION_QUERY.fullmatch(text) or _GENERIC_TIME_QUERY.fullmatch(text):
        return "all"
    return None


def is_timer_status_query(user_text: str) -> bool:
    return classify_timer_query(user_text) is not None


# The UI used this spelling previously; it remains a read-only predicate.
is_timer_status_request = is_timer_status_query


def _seconds(value: object) -> float:
    if type(value) not in (int, float):
        raise ValueError("타이머 값은 유한한 음이 아닌 초 단위 숫자여야 합니다.")
    try:
        result = float(value)
    except (OverflowError, ValueError):
        raise ValueError("타이머 값은 유한한 음이 아닌 초 단위 숫자여야 합니다.") from None
    if not math.isfinite(result) or result < 0:
        raise ValueError("타이머 값은 유한한 음이 아닌 초 단위 숫자여야 합니다.")
    return result


@dataclass(frozen=True)
class TimerSnapshot:
    current_time: datetime
    active_seconds: float
    continuous_seconds: float
    away_seconds: float
    runtime_seconds: float
    is_away: bool = False

    def __post_init__(self):
        if not isinstance(self.current_time, datetime) or type(self.is_away) is not bool:
            raise ValueError("현재 시각과 자리비움 상태를 확인할 수 없습니다.")
        for name in ("active_seconds", "continuous_seconds", "away_seconds", "runtime_seconds"):
            object.__setattr__(self, name, _seconds(getattr(self, name)))


def format_duration(seconds: float) -> str:
    """Floor elapsed partial seconds and retain seconds even beyond an hour."""
    total = int(_seconds(seconds))
    hours, rest = divmod(total, 3600)
    minutes, seconds = divmod(rest, 60)
    if hours:
        return f"{hours}시간 {minutes}분 {seconds}초"
    if minutes:
        return f"{minutes}분 {seconds}초"
    return f"{seconds}초"


def format_timer_status(snapshot: TimerSnapshot, query: str = "all") -> str:
    """Format supplied facts only, with explicit counter scope and no rounding up."""
    if type(snapshot) is not TimerSnapshot or type(query) is not str or query not in QUERY_KINDS:
        raise ValueError("타이머 조회 종류와 현재 값을 확인할 수 없습니다.")
    state = "지금은 자리비움 상태야." if snapshot.is_away else "지금은 사용 중이야."
    if query == "clock":
        return f"지금 시각은 {snapshot.current_time:%H:%M:%S}이야."
    if query == "active":
        return f"오늘 실제 사용은 {format_duration(snapshot.active_seconds)}야. {state}"
    if query == "continuous":
        return f"현재 연속 사용은 {format_duration(snapshot.continuous_seconds)}야. {state}"
    if query == "away":
        return f"오늘 누적 자리비움은 {format_duration(snapshot.away_seconds)}야. {state}"
    summary = (
        f"이번 앱 실행 경과는 {format_duration(snapshot.runtime_seconds)}야. "
        f"오늘 실제 사용은 {format_duration(snapshot.active_seconds)}, "
        f"현재 연속 사용은 {format_duration(snapshot.continuous_seconds)}, "
        f"오늘 누적 자리비움은 {format_duration(snapshot.away_seconds)}야. {state}"
    )
    return f"지금 시각은 {snapshot.current_time:%H:%M:%S}이야. {summary}" if query == "all" else summary

