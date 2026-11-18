from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time as day_time, timedelta

from state import rollover_daily
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

    def __init__(self, persisted_state, clock=time.monotonic, wall=time.time, idle_provider=None, break_interval_sec=BREAK_INTERVAL_SEC, snooze_sec=SNOOZE_SEC):
        self.state = persisted_state
        self.break_interval_sec = max(1.0, float(break_interval_sec))
        self.snooze_sec = max(1.0, float(snooze_sec))
        self.clock = clock
        self.wall = wall
        if idle_provider is None:
            from windows_idle import last_input_info
            idle_provider = last_input_info
        self.idle_provider = idle_provider

        self.last_mono = self.clock()
        self.last_wall = self.wall()
        # Close the rare midnight race between startup preparation and engine
        # construction without inventing time while the application was closed.
        today = datetime.fromtimestamp(self.last_wall).date().isoformat()
        if today > self.state.daily.day:
            rollover_daily(self.state, today=today)
        self.last_input_tick = self.idle_provider()[1]
        self.manual_grace_until = 0.0
        self._restore_idle_candidates()
        if self.state.session.ignored_breaks == 0:
            self.state.session.next_break_at = self.break_interval_sec

    def set_break_interval(self, seconds: float) -> None:
        self.break_interval_sec = max(1.0, float(seconds))
        if self.state.session.ignored_breaks == 0:
            self.state.session.next_break_at = self.break_interval_sec

    def set_snooze_interval(self, seconds: float) -> None:
        self.snooze_sec = max(1.0, float(seconds))

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
        s.idle_candidate_days.clear()

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

    def current_away_duration(self) -> float:
        """Read the ongoing away interval without recording another timer tick.

        Automatic idle classification backdates the start to the last input;
        the display must include that interval, not start counting at detection.
        """
        if not self.state.session.is_away:
            return 0.0
        return self._away_duration(self.clock(), self.wall())

    def start_manual_away(self):
        _, tick = self.idle_provider()
        s, d = self.state.session, self.state.daily
        if not s.is_away:
            self._confirm_idle()
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
        s.next_break_at = s.continuous_seconds + self.snooze_sec

    def _restore_idle_candidates(self):
        s, d = self.state.session, self.state.daily
        if s.idle_candidate_seconds and not s.idle_candidate_days:
            pending = min(s.idle_candidate_seconds, s.day_continuous_seconds, d.active_seconds)
            if pending > 0:
                s.idle_candidate_days[d.day] = [pending, s.day_continuous_seconds]

    def _day_stats(self, day):
        if self.state.daily.day == day:
            return self.state.daily
        return next((d for d in self.state.history if d.day == day), None)

    def _confirm_idle(self):
        s = self.state.session
        for day, (_, continuous) in s.idle_candidate_days.items():
            d = self._day_stats(day)
            if d is not None:
                d.longest_continuous_today = max(d.longest_continuous_today, continuous)
        s.idle_candidate_days.clear()
        s.idle_candidate_seconds = 0.0

    def _interval_parts(self, elapsed):
        """Split a measured duration at local midnights, including DST days.

        The clock remains monotonic; wall time only locates that duration on
        calendar days. When the wall clock moves back into an archived day,
        retain new measured time in the current day instead of rewriting history.
        """
        end = self.last_wall
        start = end - elapsed
        if datetime.fromtimestamp(end).date().isoformat() < self.state.daily.day:
            yield self.state.daily.day, elapsed
            return
        cursor = start
        while cursor < end:
            day = datetime.fromtimestamp(cursor).date()
            midnight = datetime.combine(day + timedelta(days=1), day_time()).timestamp()
            stop = min(end, midnight)
            yield day.isoformat(), stop - cursor
            cursor = stop

    def _select_day(self, day):
        # New measured intervals must never rewrite an archived day, including
        # the tick that crosses the same midnight again after a clock rollback.
        # Deliberate idle reclassification uses _day_stats separately.
        if day > self.state.daily.day:
            rollover_daily(self.state, today=day)
        return self.state.daily

    def _finish_calendar_tick(self):
        day = datetime.fromtimestamp(self.last_wall).date().isoformat()
        previous_day = datetime.fromtimestamp(self._previous_wall).date().isoformat()
        if day > previous_day and day > self.state.daily.day:
            rollover_daily(self.state, today=day)

    def _record_active(self, elapsed: float, provisional_idle: bool):
        if elapsed <= 0:
            return
        s = self.state.session
        for day, seconds in self._interval_parts(elapsed):
            d = self._select_day(day)
            d.active_seconds += seconds
            s.continuous_seconds += seconds
            s.day_continuous_seconds += seconds
            if provisional_idle:
                s.idle_candidate_seconds += seconds
                previous = s.idle_candidate_days.get(d.day, [0, 0])[0]
                s.idle_candidate_days[d.day] = [previous + seconds, s.day_continuous_seconds]
            else:
                self._finalize_longest()
        self._finish_calendar_tick()

    def _record_away(self, elapsed: float, manual: bool):
        if elapsed <= 0:
            return
        for day, seconds in self._interval_parts(elapsed):
            d = self._select_day(day)
            d.away_seconds += seconds
            if manual:
                d.manual_away_seconds += seconds
            else:
                d.auto_away_seconds += seconds
        self._finish_calendar_tick()

    def _reclassify_idle(self):
        s = self.state.session
        total = 0.0
        for day, (pending, _) in s.idle_candidate_days.items():
            d = self._day_stats(day)
            if d is None:
                continue
            seconds = min(pending, d.active_seconds)
            d.active_seconds -= seconds
            d.away_seconds += seconds
            d.auto_away_seconds += seconds
            if seconds > 0:
                d.away_count += 1
            if d is self.state.daily:
                s.day_continuous_seconds = max(0.0, s.day_continuous_seconds - seconds)
            total += seconds
        s.continuous_seconds = max(0.0, s.continuous_seconds - total)
        return total

    def _handle_long_gap(
        self,
        gap: float,
        now_mono: float,
        now_wall: float,
        input_changed: bool,
        result: TickResult,
        prior_away_duration: float,
    ) -> TickResult:
        """Treat an unobservable scheduler/sleep gap as away, never active."""
        s, d = self.state.session, self.state.daily
        was_away = s.is_away
        was_manual = s.manual_away

        if not was_away:
            self._finalize_longest()
            first_recorded_day = next(self._interval_parts(gap))[0]
            if first_recorded_day <= d.day:
                d.away_count += 1
            s.away_started_wall = now_wall - gap

        # Some clocks pause during suspend. Keep the display/return duration in
        # step with the same gap already attributed to away statistics, without
        # recording it again. A virtual monotonic anchor may precede clock zero.
        s.away_started_mono = now_mono - (prior_away_duration + gap)

        # Mark the interval away before splitting so each new day counts the
        # same ongoing interval once.
        s.is_away = True
        self._confirm_idle()
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

        return result

    def tick(self) -> TickResult:
        result = TickResult()
        now_mono = self.clock()
        now_wall = self.wall()

        previous_mono, previous_wall = self.last_mono, self.last_wall
        self._previous_wall = previous_wall
        mono_gap = max(0.0, now_mono - previous_mono)
        wall_gap = max(0.0, now_wall - previous_wall)
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
                self._away_duration(previous_mono, previous_wall) if s.is_away else 0.0,
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
            self._confirm_idle()
            self._record_active(elapsed, provisional_idle=False)
        elif idle_sec < IDLE_THRESHOLD_SEC:
            self._record_active(elapsed, provisional_idle=True)
        else:
            # Five minutes without input: retroactively reclassify the entire
            # provisional no-input interval as away, including the current tick.
            counted_today = s.idle_candidate_days.get(d.day, [0, 0])[0] > 0
            candidate = self._reclassify_idle()
            self._finalize_longest()
            away_elapsed = candidate + elapsed
            if not counted_today:
                d.away_count += 1
            s.is_away = True
            self._record_away(elapsed, manual=False)
            s.manual_away = False
            s.away_started_wall = now_wall - away_elapsed
            s.away_started_mono = now_mono - away_elapsed
            self._reset_active_session()
            result.became_away = True
            return result

        if s.continuous_seconds >= s.next_break_at:
            result.break_due = True
        return result
