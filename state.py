from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from datetime import date
import json
import os
from pathlib import Path
import time

SCHEMA_VERSION = 5


@dataclass
class DailyStats:
    day: str = ""
    active_seconds: float = 0.0
    away_seconds: float = 0.0
    manual_away_seconds: float = 0.0
    auto_away_seconds: float = 0.0
    away_count: int = 0
    longest_continuous_today: float = 0.0

    @classmethod
    def today(cls) -> "DailyStats":
        return cls(day=date.today().isoformat())


@dataclass
class SessionState:
    # Continuous active use may span midnight.
    continuous_seconds: float = 0.0
    # Portion of the current continuous session that belongs to today's stats.
    day_continuous_seconds: float = 0.0
    next_break_at: float = 3600.0
    ignored_breaks: int = 0
    is_away: bool = False
    manual_away: bool = False
    away_started_wall: float | None = None
    last_seen_wall: float = 0.0


@dataclass
class PersistedState:
    schema_version: int
    daily: DailyStats
    session: SessionState


_FLOAT_FIELDS = {
    "active_seconds",
    "away_seconds",
    "manual_away_seconds",
    "auto_away_seconds",
    "longest_continuous_today",
    "continuous_seconds",
    "day_continuous_seconds",
    "next_break_at",
    "away_started_wall",
    "last_seen_wall",
}
_INT_FIELDS = {"away_count", "ignored_breaks"}
_BOOL_FIELDS = {"is_away", "manual_away"}


def _coerce(cls, data: dict):
    out = {}
    known = {f.name for f in fields(cls)}
    for name in known:
        if name not in data:
            continue
        value = data[name]
        try:
            if name in _FLOAT_FIELDS:
                out[name] = None if value is None else float(value)
            elif name in _INT_FIELDS:
                out[name] = int(value)
            elif name in _BOOL_FIELDS:
                if isinstance(value, str):
                    out[name] = value.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    out[name] = bool(value)
            elif name == "day":
                out[name] = str(value)
        except (TypeError, ValueError):
            # Bad individual values fall back to dataclass defaults.
            pass
    return cls(**out)


def fresh_state() -> PersistedState:
    return PersistedState(SCHEMA_VERSION, DailyStats.today(), SessionState())


def load_state(path: Path) -> PersistedState:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        daily = _coerce(DailyStats, raw.get("daily", {}))
        session = _coerce(SessionState, raw.get("session", {}))
        if not daily.day:
            daily.day = date.today().isoformat()
        return PersistedState(
            int(raw.get("schema_version", SCHEMA_VERSION)),
            daily,
            session,
        )
    except FileNotFoundError:
        return fresh_state()
    except Exception:
        # Preserve damaged input for diagnosis instead of silently deleting it.
        try:
            corrupt = path.with_name(path.name + f".{int(time.time())}.corrupt")
            path.replace(corrupt)
        except Exception:
            pass
        return fresh_state()


def save_state(path: Path, state: PersistedState, now_wall: float | None = None):
    path.parent.mkdir(parents=True, exist_ok=True)
    state.session.last_seen_wall = float(now_wall if now_wall is not None else time.time())
    payload = {
        "schema_version": SCHEMA_VERSION,
        "daily": asdict(state.daily),
        "session": asdict(state.session),
    }
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def rollover_daily(state: PersistedState, today: str | None = None):
    """Reset daily counters without breaking an in-progress session.

    The global continuous session and break schedule survive midnight. Today's
    longest-continuous statistic starts from zero, because time worked before
    midnight must not be reported as today's work.
    """
    today = today or date.today().isoformat()
    if state.daily.day == today:
        return

    was_away = state.session.is_away
    state.daily = DailyStats(day=today)
    state.session.day_continuous_seconds = 0.0
    if was_away:
        # One away period is already in progress at the start of the new day.
        state.daily.away_count = 1


def reset_untracked_session(
    state: PersistedState,
    now_wall: float,
    tolerance_sec: float = 60.0,
) -> float:
    """Reset continuity after an app shutdown/outage longer than tolerance.

    Downtime is intentionally not added to active or away totals because the app
    cannot know whether the PC was being used while it was not running.
    """
    last = state.session.last_seen_wall
    if last <= 0:
        state.session = SessionState()
        return 0.0

    gap = max(0.0, now_wall - last)
    if gap > tolerance_sec:
        state.session = SessionState()
    return gap
