from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from settings import WORKDAY


@dataclass(frozen=True)
class WorkdayState:
    mode: str
    message: str | None


def classify_workday(now: datetime, active_seconds: float, policy=WORKDAY) -> WorkdayState:
    t = now.time()
    if active_seconds >= policy.hard_active_limit_sec:
        return WorkdayState("hard_stop", "오늘 실사용 9시간이야. 이제는 진짜 끝내자.")
    if t >= policy.late_leave:
        return WorkdayState("late_leave", "야근 알림 시간이 지났어. 오늘 일은 여기서 닫자.")
    if t >= policy.strong_leave:
        return WorkdayState("strong_leave", "이제 퇴근할 시간이야. 새 일 벌이지 말고 정리하자.")
    if t >= policy.leave_mode:
        return WorkdayState("leave", "퇴근 모드로 갈게. 하던 것만 마무리하자.")
    if t >= policy.wind_down:
        return WorkdayState("wind_down", "슬슬 오늘 할 일 정리할 시간이야.")
    return WorkdayState("normal", None)


def apply_reminder_preference(state: WorkdayState, enabled: bool) -> WorkdayState:
    """Hide clock-based reminders while preserving the active-time safety stop."""
    if enabled or state.mode == "hard_stop":
        return state
    return WorkdayState("normal", None)


def should_encourage_more_work(mode: str) -> bool:
    return mode in {"normal", "wind_down"}
