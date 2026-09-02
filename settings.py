from __future__ import annotations

from dataclasses import dataclass
from datetime import time as dt_time

@dataclass(frozen=True)
class WorkdayPolicy:
    usual_start: dt_time = dt_time(8, 40)
    wind_down: dt_time = dt_time(17, 0)
    leave_mode: dt_time = dt_time(17, 30)
    strong_leave: dt_time = dt_time(18, 0)
    late_leave: dt_time = dt_time(18, 30)
    hard_active_limit_sec: int = 9 * 60 * 60

WORKDAY = WorkdayPolicy()
