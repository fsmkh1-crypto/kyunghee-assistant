from __future__ import annotations
from dataclasses import dataclass
import time

IDLE_THRESHOLD_SEC = 5 * 60
BREAK_INTERVAL_SEC = 60 * 60
SNOOZE_SEC = 5 * 60
GAP_TOLERANCE_SEC = 90.0
MANUAL_INPUT_GRACE_SEC = 3.0

@dataclass
class TickResult:
    became_away: bool = False
    became_active: bool = False
    break_due: bool = False
    away_duration: float = 0.0
    manual_resumed_by_input: bool = False
    long_gap: bool = False

class TimerEngine:
    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None):
        self.state = persisted_state
        self.clock = clock
        self.wall = wall
        if idle_provider is None:
            from windows_idle import last_input_info
            idle_provider = last_input_info
        self.idle_provider = idle_provider
        self.last_mono = self.clock()
        self.last_wall = self.wall()
        self.last_input_tick = self.idle_provider()[1]
        self.manual_grace_until = 0.0

    def remaining_to_break(self) -> float:
        s = self.state.session
        return max(0.0, s.next_break_at - s.continuous_seconds)

    def _reset_session_after_away(self):
        s = self.state.session
        s.manual_away = False
        s.is_away = False
        s.away_started_wall = None
        s.continuous_seconds = 0.0
        s.next_break_at = BREAK_INTERVAL_SEC
        s.ignored_breaks = 0

    def start_manual_away(self):
        _, tick = self.idle_provider()
        s = self.state.session
        if not s.is_away:
            self.state.daily.away_count += 1
        s.manual_away = True
        s.is_away = True
        s.away_started_wall = self.wall()
        self.last_input_tick = tick
        self.manual_grace_until = self.clock() + MANUAL_INPUT_GRACE_SEC

    def stop_manual_away(self):
        self._reset_session_after_away()

    def accept_break(self):
        self.start_manual_away()
        s = self.state.session
        s.continuous_seconds = 0.0
        s.next_break_at = BREAK_INTERVAL_SEC
        s.ignored_breaks = 0

    def snooze_break(self):
        s = self.state.session
        s.ignored_breaks += 1
        s.next_break_at = s.continuous_seconds + SNOOZE_SEC

    def tick(self) -> TickResult:
        result = TickResult()
        now_mono = self.clock()
        now_wall = self.wall()
        mono_gap = max(0.0, now_mono - self.last_mono)
        wall_gap = max(0.0, now_wall - self.last_wall)
        elapsed = mono_gap
        self.last_mono, self.last_wall = now_mono, now_wall

        idle_sec, input_tick = self.idle_provider()
        input_changed = input_tick != self.last_input_tick
        self.last_input_tick = input_tick
        s, d = self.state.session, self.state.daily

        if max(mono_gap, wall_gap) > GAP_TOLERANCE_SEC:
            gap = max(mono_gap, wall_gap)
            d.away_seconds += gap
            if s.manual_away:
                d.manual_away_seconds += gap
            else:
                d.auto_away_seconds += gap
                if not s.is_away:
                    d.away_count += 1
            result.long_gap = True
            result.became_active = True
            result.away_duration = gap
            self._reset_session_after_away()
            return result

        if s.manual_away:
            if input_changed and now_mono >= self.manual_grace_until:
                d.away_seconds += elapsed
                d.manual_away_seconds += elapsed
                result.manual_resumed_by_input = True
                result.became_active = True
                result.away_duration = max(0.0, now_wall - (s.away_started_wall or now_wall))
                self._reset_session_after_away()
                return result
            d.away_seconds += elapsed
            d.manual_away_seconds += elapsed
            return result

        if idle_sec >= IDLE_THRESHOLD_SEC:
            away_part = min(elapsed, max(0.0, idle_sec - IDLE_THRESHOLD_SEC))
            active_part = max(0.0, elapsed - away_part)
            if active_part:
                d.active_seconds += active_part
                s.continuous_seconds += active_part
                d.longest_continuous_today = max(d.longest_continuous_today, s.continuous_seconds)
            if away_part:
                d.away_seconds += away_part
                d.auto_away_seconds += away_part
            if not s.is_away:
                s.is_away = True
                s.away_started_wall = now_wall - max(0.0, idle_sec - IDLE_THRESHOLD_SEC)
                d.away_count += 1
                result.became_away = True
            return result

        if s.is_away:
            result.became_active = True
            result.away_duration = max(0.0, now_wall - (s.away_started_wall or now_wall))
            self._reset_session_after_away()

        d.active_seconds += elapsed
        s.continuous_seconds += elapsed
        d.longest_continuous_today = max(d.longest_continuous_today, s.continuous_seconds)
        if s.continuous_seconds >= s.next_break_at:
            result.break_due = True
        return result
