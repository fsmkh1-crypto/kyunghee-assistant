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
    """Platform-independent timer state machine.

    `clock`, `wall`, and `idle_provider` are injected so all timing edge cases can
    be reproduced in unit tests without Windows.
    """

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
        # Short idle time is provisionally active. If it reaches five minutes,
        # the entire no-input interval is reclassified as away time.
        self.idle_candidate_seconds = 0.0

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
        s.next_break_at = BREAK_INTERVAL_SEC
        s.ignored_breaks = 0
        self.idle_candidate_seconds = 0.0

    def _clear_away(self):
        s = self.state.session
        s.manual_away = False
        s.is_away = False
        s.away_started_wall = None
        self._reset_active_session()

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
        # The click that starts the break must never count as a resume signal.
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
            self.idle_candidate_seconds += elapsed
        else:
            self.idle_candidate_seconds = 0.0
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
        now_wall: float,
        idle_sec: float,
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

        self._record_away(gap, manual=was_manual)
        self._reset_active_session()
        result.long_gap = True

        # A long unobserved gap ends only when a genuinely new Windows input is
        # seen. A small idle value alone is not sufficient evidence of return.
        resumed_now = input_changed
        if resumed_now:
            result.became_active = True
            result.manual_resumed_by_input = was_manual
            result.away_duration = gap if not s.away_started_wall else max(
                0.0, now_wall - s.away_started_wall
            )
            s.is_away = False
            s.manual_away = False
            s.away_started_wall = None
        else:
            if not was_away:
                result.became_away = True
            s.is_away = True
            s.manual_away = False
            s.away_started_wall = s.away_started_wall or (now_wall - gap)

        return result

    def tick(self) -> TickResult:
        result = TickResult()
        now_mono = self.clock()
        now_wall = self.wall()

        mono_gap = max(0.0, now_mono - self.last_mono)
        # wall time is diagnostic only; accumulation uses monotonic time so NTP
        # or manual clock adjustments cannot create fake work.
        self.last_mono = now_mono
        self.last_wall = now_wall
        elapsed = mono_gap

        idle_sec, input_tick = self.idle_provider()
        input_changed = input_tick != self.last_input_tick
        self.last_input_tick = input_tick
        s, d = self.state.session, self.state.daily

        if elapsed > GAP_TOLERANCE_SEC:
            return self._handle_long_gap(
                elapsed,
                now_wall,
                idle_sec,
                input_changed,
                result,
            )

        # Manual away: the starting click is masked by the grace period. A later
        # input resumes the session, and the entire resume tick remains away.
        if s.manual_away:
            self._record_away(elapsed, manual=True)
            if input_changed and now_mono >= self.manual_grace_until:
                result.manual_resumed_by_input = True
                result.became_active = True
                result.away_duration = max(
                    0.0, now_wall - (s.away_started_wall or now_wall)
                )
                self._clear_away()
            return result

        # Auto-away return: keep this transition tick as away because the exact
        # moment of the user's input inside the one-second interval is unknown.
        if s.is_away and input_changed:
            self._record_away(elapsed, manual=False)
            result.became_active = True
            result.away_duration = max(
                0.0, now_wall - (s.away_started_wall or now_wall)
            )
            self._clear_away()
            return result

        if s.is_away:
            self._record_away(elapsed, manual=False)
            return result

        # A fresh input confirms all short-idle time accumulated so far as real
        # use. It remains in active_seconds and can now contribute to longest.
        if input_changed:
            self.idle_candidate_seconds = 0.0
            self._record_active(elapsed, provisional_idle=False)
        elif idle_sec < IDLE_THRESHOLD_SEC:
            # Short no-input intervals are provisionally treated as active.
            self._record_active(elapsed, provisional_idle=True)
        else:
            # Five minutes without input: retroactively reclassify the whole
            # candidate interval as away, including the current tick.
            candidate = min(
                self.idle_candidate_seconds,
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
            self._reset_active_session()
            result.became_away = True
            return result

        if s.continuous_seconds >= s.next_break_at:
            result.break_due = True
        return result
