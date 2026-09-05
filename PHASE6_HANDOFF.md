# Phase 6 Handoff — Work / Break Behavior

## Status

CODE INTEGRATED / MULTI-DAY REAL-WORLD VALIDATION PENDING.

## Completed behavior to preserve

- Configurable break interval: 20–180 minutes, default 60.
- Configurable snooze interval: 1–30 minutes, default 5.
- Break popup text reflects the actual configured snooze duration.
- “오늘은 그만” suppresses break reminders for the current local day only and survives restart.
- Daily suppression resets automatically after local day rollover.
- Manual away / return behavior remains independent from break-reminder suppression.
- Sleep/lock gaps remain treated as away according to the existing timer engine policy.
- Workday wind-down / leave / strong-leave / late-leave / 9-hour hard-stop behavior remains intact.
- Fullscreen/presentation mode hides break alerts without consuming the reminder gate.
- When presentation mode ends, a still-due break reminder may appear immediately on the next check.

## Remaining Phase 6 work

- Multi-day real-world use to catch timing or rollover regressions that CI cannot reproduce reliably.
- Refine manual/automatic away or workday policy only if real usage exposes a concrete problem.
- Pomodoro mode remains optional and deferred; do not add it merely to close the phase.

## Constraints

- Preserve all Phase 1–5 behavior unless a verified regression requires change.
- Operational reminders always outrank personality/custom/rare/daily dialogue.
- Do not mark Phase 6 fully complete until multi-day real-world use is satisfactory.
