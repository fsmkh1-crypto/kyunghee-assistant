# Phase 6 Handoff — Work / Break Behavior

## Status

ACTIVE / BREAK AND SNOOZE INTERVAL SETTINGS INTEGRATED.

## Existing baseline to preserve

- Continuous PC-use tracking and 60-minute break reminder.
- 5-minute snooze flow.
- Manual rest and away/return tracking.
- Sleep/lock gaps treated as away.
- Workday wind-down / leave / strong-leave / late-leave / 9-hour hard-stop policy.
- Fullscreen/presentation suppression infrastructure already exists.

## Phase 6 priority

1. Configurable break interval while keeping 60 minutes as the default.
2. Configurable snooze duration / reminder behavior without making the settings noisy.
3. “Stop reminders for today” with a clear reset at the next workday/day boundary.
4. Refine work start/end and manual/automatic away policy where real usage shows a need.
5. Ensure fullscreen/presentation deferral resumes reminders correctly.
6. Optional Pomodoro mode only after the above is stable.

## Constraints

- Preserve all Phase 1–5 behavior unless a verified regression requires change.
- Operational reminders always outrank personality/custom/rare/daily dialogue.
- Multi-day real-world use is required before Phase 6 can be marked complete.
