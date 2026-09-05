from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from state import DailyStats, PersistedState


@dataclass(frozen=True)
class RecentStatsSummary:
    days: int
    tracked_days: int
    active_seconds: float
    away_seconds: float
    away_count: int
    longest_continuous: float
    average_active_seconds: float
    active_ratio: float
    best_day: str | None
    best_day_active_seconds: float


def _day_has_activity(item: DailyStats) -> bool:
    return bool(
        item.active_seconds
        or item.away_seconds
        or item.away_count
        or item.longest_continuous_today
    )


def recent_daily_stats(
    state: PersistedState,
    *,
    days: int = 7,
    today: str | None = None,
) -> list[DailyStats]:
    """Return a calendar-aligned window, oldest first, with missing days as zeros."""
    days = max(1, int(days))
    try:
        end = date.fromisoformat(today or state.daily.day or date.today().isoformat())
    except ValueError:
        end = date.today()

    by_day = {item.day: item for item in state.history if item.day}
    if state.daily.day:
        by_day[state.daily.day] = state.daily

    rows: list[DailyStats] = []
    start = end - timedelta(days=days - 1)
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        rows.append(by_day.get(day, DailyStats(day=day)))
    return rows


def summarize_recent(
    state: PersistedState,
    *,
    days: int = 7,
    today: str | None = None,
) -> RecentStatsSummary:
    rows = recent_daily_stats(state, days=days, today=today)
    tracked = [item for item in rows if _day_has_activity(item)]
    active = sum(item.active_seconds for item in rows)
    away = sum(item.away_seconds for item in rows)
    total = active + away
    best = max(rows, key=lambda item: item.active_seconds, default=None)
    if best is None or best.active_seconds <= 0:
        best_day = None
        best_seconds = 0.0
    else:
        best_day = best.day
        best_seconds = best.active_seconds
    return RecentStatsSummary(
        days=len(rows),
        tracked_days=len(tracked),
        active_seconds=active,
        away_seconds=away,
        away_count=sum(item.away_count for item in rows),
        longest_continuous=max((item.longest_continuous_today for item in rows), default=0.0),
        average_active_seconds=active / len(tracked) if tracked else 0.0,
        active_ratio=(active / total * 100.0) if total else 0.0,
        best_day=best_day,
        best_day_active_seconds=best_seconds,
    )


def stats_reaction(summary: RecentStatsSummary) -> str:
    """Small, deterministic Kyunghee reaction based on recent usage only."""
    if summary.tracked_days == 0:
        return "아직 7일 기록이 비어 있네. 오늘부터 천천히 쌓아보자."
    if summary.longest_continuous >= 2 * 3600:
        return "길게 집중한 날이 있었네. 잘했는데, 다음엔 중간에 한 번은 꼭 쉬어."
    if summary.tracked_days >= 5 and summary.active_ratio >= 80:
        return "이번 주 흐름 꽤 좋다. 집중할 땐 확실히 했네."
    if summary.active_seconds >= 20 * 3600:
        return "이번 주 많이 달렸네. 기록도 좋지만 쉬는 시간도 같이 챙기자."
    if summary.tracked_days >= 3:
        return "기록이 제법 쌓였네. 무리하지 말고 이 페이스로 가자."
    return "기록이 쌓이기 시쮑했네. 며칠만 더 써보면 흐름이 더 잘 보여."
