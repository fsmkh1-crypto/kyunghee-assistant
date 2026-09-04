from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BreakReminderGate:
    """Pure state machine controlling repeated break reminders.

    UI windows may be replaced or destroyed independently. The reminder gate
    remembers when the last break reminder was shown and allows another one once
    the repeat interval expires. Session reset/accept/snooze explicitly re-arm it.
    """

    repeat_interval_sec: float = 5 * 60
    armed: bool = False
    last_shown_at: float = 0.0

    def should_show(self, break_due: bool, now: float) -> bool:
        if not break_due:
            return False
        if not self.armed:
            self.armed = True
            self.last_shown_at = now
            return True
        if now - self.last_shown_at >= self.repeat_interval_sec:
            self.last_shown_at = now
            return True
        return False

    def defer(self) -> None:
        """Forget a hidden reminder so a still-due break can show immediately later."""
        self.armed = False
        self.last_shown_at = 0.0

    def reset(self) -> None:
        self.defer()
