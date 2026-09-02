# External review checklist (Claude / other reviewers)

Please review the **current `main` branch** as a Windows desktop productivity timer.

## Primary correctness requirements

1. 60 minutes of active use triggers a break reminder.
2. Snooze moves the next reminder by exactly 5 minutes, repeatedly.
3. Clicking `Away` or `I'll take a break` must not auto-resume from the click itself.
4. A later keyboard/mouse input should resume a manual-away session.
5. A long scheduler/sleep gap must never become active time, even when the wake-up key resets idle time.
6. App downtime over 60 seconds resets the continuous session on restart.
7. Daily counters roll over at midnight without corrupting current state.
8. Multiple launches must be blocked (single-instance mutex).
9. UI break-alert state must be re-armed after session reset and must not get stuck forever.
10. Toast auto-close callbacks must close only the toast that scheduled them.
11. State writes must be atomic and recover from corrupt JSON.
12. Reproducible timer-engine tests must run without Windows by injecting clock/wall/idle providers.

## Workday behavior

Default work pattern:
- arrival around 08:40
- wind-down from 17:00
- leaving-work mode from 17:30
- stronger leave-work prompts from 18:00
- late-work nagging from 18:30
- 9 hours of actual active use is a hard upper warning threshold

The app should not encourage more work once leave-work mode is active.

## Privacy

Confirm the code only reads last-input timing metadata and does not capture keystrokes, typed text, window titles, clipboard contents, or browser data.

## Review format

For every issue:
1. Title
2. Reproduction
3. Current behavior
4. Expected behavior
5. Severity: Critical / High / Medium / Low
6. Minimal fix
7. Optional patch example

End with:
- Is this version ready for real-world testing?
- Must-fix items before testing
- Items safe to defer
