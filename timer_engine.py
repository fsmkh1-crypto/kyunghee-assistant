from __future__ import annotations

from dataclasses import dataclass
import time

IDLE_THRESHOLD_SEC = 5 * 60
BREAK_INTERVAL_SEC = 60 * 60
SNOOZE_SEC = 5 * 60
GAP_TOLERANCE_SEC = 90.0
MAX_GAP_SEC = 24 * 60 * 60
MANUAL_INPUT_GRACE_SEC = 15.0


@dataclass
class TickResult:
    became_away: bool = False
    became_active: bool = False
    break_due: bool = False
    away_duration: float = 0.0
    manual_resumed_by_input: bool = False
    long_gap: bool = False


class TimerEngine:
    """Platform-independent timer state machine.

    `clock`, `wall`, and `idle_provider` are injected so edge cases can be
    reproduced in unit tests without Windows.
    """

    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None, break_interval_sec=BREAK_INTERVAL_SEC):
        self.state = persisted_state
        self.break_interval_sec = max(1.0, float(break_interval_sec))
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
        if self.state.session.ignored_breaks == 0:
            self.state.session.next_break_at = self.break_interval_sec

    def set_break_interval(self, seconds: float) -> None:
        self.break_interval_sec = max(1.0, float(seconds))
        if self.state.session.ignored_breaks == 0:
            self.state.session.next_break_at = self.break_interval_sec

    def remaining_to_break(self) -> float:
        s = self.state.session
        return max(0.0, s.next_break_at - s.continuous_seconds)

    def _finalize_longest(self):
        d, s = self.state.daily, self.state.session
        d.longest_continuous_today = max(
            d.longest_continuous_today,
            max(0.0, s.day_continuous_seconds),
        )

    def _reset_active_session(self):
        s = self.state.session
        s.continuous_seconds = 0.0
        s.day_continuous_seconds = 0.0
        s.next_break_at = self.break_interval_sec
        s.ignored_breaks = 0
        s.idle_candidate_seconds = 0.0

    def _clear_away(self):
        s = self.state.session
        s.manual_away = False
        s.is_away = False
        s.away_started_wall = None
        s.away_started_mono = None
        self._reset_active_session()

    def _away_duration(self, now_mono: float, now_wall: float) -> float:
        s = self.state.session
        if s.away_started_mono is not None:
            return max(0.0, now_mono - s.away_started_mono)
        if s.away_started_wall is not None:
            return max(0.0, now_wall - s.away_started_wall)
        return 0.0

    def start_manual_away(self):
        _, tick = self.idle_provider()
        s, d = self.state.session, self.state.daily
        if not s.is_away:
            self._finalize_longest()
            d.away_count += 1
        self._reset_active_session()
        s.manual_away = True
        s.is_away = True
        s.away_started_wall = self.wall()
        s.away_started_mono = self.clock()
        # Ignore incidental pointer motion immediately after clicking Away.
        self.last_input_tick = tick
        self.manual_grace_until = self.clock() + MANUAL_INPUT_GRACE_SEC

    def stop_manual_away(self):
        self._clear_away()

    def accept_break(self):
        self.start_manual_away()

    def snooze_break(self):
        s = self.state.session
        s.ignored_breaks += 1
        s.next_break_at = s.continuous_seconds + SNOOZE_SEC

    def _record_active(self, elapsed: float, provisional_idle: bool):
        if elapsed <= 0:
            return
        d, s = self.state.daily, self.state.session
        d.active_seconds += elapsed
        s.continuous_seconds += elapsed
        s.day_continuous_seconds += elapsed
        if provisional_idle:
            s.idle_candidate_seconds += elapsed
        else:
            s.idle_candidate_seconds = 0.0
            self._finalize_longest()

    def _record_away(self, elapsed: float, manual: bool):
        if elapsed <= 0:
            return
        d = self.state.daily
        d.away_seconds += elapsed
        if manual:
            d.manual_away_seconds += elapsed
        else:
            d.auto_away_seconds += elapsed

    def _handle_long_gap(
        self,
        gap: float,
        now_mono: float,
        now_wall: float,
        input_changed: bool,
        result: TickResult,
    ) -> TickResult:
        """Treat an unobservable scheduler/sleep gap as away, never active."""
        s, d = self.state.session, self.state.daily
        was_away = s.is_away
        was_manual = s.manual_away

        if not was_away:
            self._finalize_longest()
            d.away_count += 1
            s.away_started_wall = now_wall - gap
            s.away_started_mono = now_mono - min(gap, now_mono)

        self._record_away(gap, manual=was_manual)
        self._reset_active_session()
        result.long_gap = True

        # A long unobserved gap ends only when genuinely fresh Windows input is
        # seen. A small idle value alone is not sufficient evidence of return.
        if input_changed:
            result.became_active = True
            result.manual_resumed_by_input = was_manual
            result.away_duration = self._away_duration(now_mono, now_wall)
            self._clear_away()
        else:
            if not was_away:
                result.became_away = True
            s.is_away = True
            s.manual_away = was_manual
            if s.away_started_wall is None:
                s.away_started_wall = now_wall - gap
            if s.away_started_mono is None:
                s.away_started_mono = now_mono - min(gap, now_mono)

        return result

    def tick(self) -> TickResult:
        result = TickResult()
        now_mono = self.clock()
        now_wall = self.wall()

        mono_gap = max(0.0, now_mono - self.last_mono)
        wall_gap = max(0.0, now_wall - self.last_wall)
        self.last_mono = now_mono
        self.last_wall = now_wall
        elapsed = mono_gap

        idle_sec, input_tick = self.idle_provider()
        input_changed = input_tick != self.last_input_tick
        self.last_input_tick = input_tick
        s, d = self.state.session, self.state.daily

        # Monotonic time remains the accumulation source. Wall time is only an
        # independent detector for suspend/resume platforms where monotonic may
        # pause during sleep. A wall-clock jump can therefore create away time,
        # but can never create fake active time. Cap pathological clock changes.
        if mono_gap > GAP_TOLERANCE_SEC or wall_gap > GAP_TOLERANCE_SEC:
            gap = max(mono_gap, min(wall_gap, MAX_GAP_SEC))
            return self._handle_long_gap(
                gap,
                now_mono,
                now_wall,
                input_changed,
                result,
            )

        # Manual away: the starting click and immediate pointer cleanup are
        # masked by a short grace period. A later input resumes the session, and
        # the entire resume tick remains away.
        if s.manual_away:
            self._record_away(elapsed, manual=True)
            if input_changed and now_mono >= self.manual_grace_until:
                result.manual_resumed_by_input = True
                result.became_active = True
                result.away_duration = self._away_duration(now_mono, now_wall)
                self._clear_away()
            return result

        # Auto-away return: keep this transition tick as away because the exact
        # moment of input inside the one-second interval is unknown.
        if s.is_away and input_changed:
            self._record_away(elapsed, manual=False)
            result.became_active = True
            result.away_duration = self._away_duration(now_mono, now_wall)
            self._clear_away()
            return result

        if s.is_away:
            self._record_away(elapsed, manual=False)
            return result

        # A fresh input confirms all short-idle time accumulated so far as real
        # use. It remains in active_seconds and can contribute to longest.
        if input_changed:
            s.idle_candidate_seconds = 0.0
            self._record_active(elapsed, provisional_idle=False)
        elif idle_sec < IDLE_THRESHOLD_SEC:
            self._record_active(elapsed, provisional_idle=True)
        else:
            # Five minutes without input: retroactively reclassify the entire
            # provisional no-input interval as away, including the current tick.
            candidate = min(
                s.idle_candidate_seconds,
                d.active_seconds,
                s.continuous_seconds,
                s.day_continuous_seconds,
            )
            if candidate > 0:
                d.active_seconds -= candidate
                s.continuous_seconds -= candidate
                s.day_continuous_seconds -= candidate

            self._finalize_longest()
            away_elapsed = candidate + elapsed
            self._record_away(away_elapsed, manual=False)
            d.away_count += 1
            s.is_away = True
            s.manual_away = False
            s.away_started_wall = now_wall - away_elapsed
            s.away_started_mono = now_mono - away_elapsed
            self._reset_active_session()
            result.became_away = True
            return result

        if s.continuous_seconds >= s.next_break_at:
            result.break_due = True
        return result
