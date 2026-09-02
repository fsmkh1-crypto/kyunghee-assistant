from __future__ import annotations
from dataclasses import dataclass, asdict, fields
from datetime import date
from pathlib import Path
import json
import os
import time

SCHEMA_VERSION = 4

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
    continuous_seconds: float = 0.0
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

def _coerce(cls, data: dict):
    out = {}
    spec = {f.name: f for f in fields(cls)}
    for name, f in spec.items():
        if name not in data:
            continue
        v = data[name]
        try:
            if name in {"active_seconds","away_seconds","manual_away_seconds","auto_away_seconds","longest_continuous_today","continuous_seconds","next_break_at","away_started_wall","last_seen_wall"}:
                out[name] = None if v is None else float(v)
            elif name in {"away_count","ignored_breaks"}:
                out[name] = int(v)
            elif name in {"is_away","manual_away"}:
                out[name] = bool(v)
            elif name == "day":
                out[name] = str(v)
        except (TypeError, ValueError):
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
        return PersistedState(int(raw.get("schema_version", SCHEMA_VERSION)), daily, session)
    except FileNotFoundError:
        return fresh_state()
    except Exception:
        try:
            corrupt = path.with_name(path.name + f".{int(time.time())}.corrupt")
            path.replace(corrupt)
        except Exception:
            pass
        return fresh_state()

def save_state(path: Path, state: PersistedState, now_wall: float | None = None):
    state.session.last_seen_wall = float(now_wall if now_wall is not None else time.time())
    payload = {"schema_version": SCHEMA_VERSION, "daily": asdict(state.daily), "session": asdict(state.session)}
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)

def rollover_daily(state: PersistedState, today: str | None = None):
    today = today or date.today().isoformat()
    if state.daily.day == today:
        return
    was_away = state.session.is_away
    carried = state.session.continuous_seconds
    state.daily = DailyStats(day=today)
    if was_away:
        state.daily.away_count = 1
    else:
        state.daily.longest_continuous_today = carried

def reset_untracked_session(state: PersistedState, now_wall: float, tolerance_sec: float = 60.0) -> float:
    last = state.session.last_seen_wall
    if last <= 0:
        state.session = SessionState()
        return 0.0
    gap = max(0.0, now_wall - last)
    if gap > tolerance_sec:
        state.session = SessionState()
    return gap
