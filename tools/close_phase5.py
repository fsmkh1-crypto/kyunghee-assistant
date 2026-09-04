from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / "PROJECT_PHASES.md"
text = path.read_text(encoding="utf-8")
old = '''## Phase 5 — Personality / fun behaviors

### Status: IN PROGRESS / PERSONALITY FOUNDATION INTEGRATED

Implemented so far:
- Dialogue personality presets: balanced / warm / playful / strict.
- Settings persistence with schema version 5 and safe fallback for unknown values.
- Personality affects normal, encouragement, and character-click dialogue while work/break/leave warnings keep their existing priority and strength.
- Character short-click still opens detail as required, but leaves a character reaction line visible when returning to the compact timer.
- Time-of-day dialogue buckets: morning / lunch / afternoon / evening / late.
- Pure tests for personality selection and time buckets.

Next priority:
1. Rare dialogue / easter eggs with low-frequency, non-disruptive triggering.
2. Streak/habit reactions using reliable existing state only.
3. Custom dialogue storage and settings UI.
4. Daily/random temperament only after the above remains lightweight.

Avoid turning the app into a heavy game system.
'''
new = '''## Phase 5 — Personality / fun behaviors

### Status: COMPLETE / CODE AND SETTINGS FLOW VALIDATED

Implemented and validated:
- Dialogue personality presets: balanced / warm / playful / strict.
- Settings persistence with schema version 5 and safe fallback for unknown values.
- Personality affects normal, encouragement, and character-click dialogue while work/break/leave warnings keep their existing priority and strength.
- Character short-click still opens detail as required, but leaves a character reaction line visible when returning to the compact timer.
- Time-of-day dialogue buckets: morning / lunch / afternoon / evening / late.
- Rare dialogue / easter eggs at low frequency with a minimum-gap guard so they do not cluster.
- Habit reactions use existing reliable state only; no score, affinity, level, or heavy game system was introduced.
- User custom dialogue accepts multiple lines, is bounded/sanitized, and is mixed only into normal dialogue so operational reminders are never replaced.
- Lightweight daily temperament uses a date-stable calm / bright / focused mood and only occasionally affects normal dialogue.
- Phase 5 dialogue helpers have deterministic unit-test hooks for probability and date behavior.
- Existing Phase 1–4 window, image, warning, leave-work, and transparency priorities remain unchanged.

Extended real-world personality tuning can continue during normal use, but no Phase 5 blocker remains.
'''
if old not in text:
    raise SystemExit("Phase 5 section did not match expected text")
text = text.replace(old, new, 1)
text = text.replace('2. Read `PHASE5_HANDOFF.md` (Phase 4 handoff is historical).', '2. Read `PHASE6_HANDOFF.md` for the active workstream; Phase 5 is historical.', 1)
text = text.replace('10. Phase 4 is complete; preserve the image-set/preview system. Phase 5 is active.', '10. Phases 4 and 5 are complete; preserve the image-set/preview and personality systems. Phase 6 is active.', 1)
text = text.replace('- Phase 5 personality foundation is now the active workstream.', '- Phase 5 personality/fun behavior scope is complete; Phase 6 work/break behavior is now active.', 1)
path.write_text(text, encoding="utf-8")

handoff = '''# Phase 5 Handoff — Personality / Fun Behaviors

## Status

COMPLETE. This file is historical; active work moves to Phase 6.

## Integrated behavior

- Personality presets: balanced / warm / playful / strict.
- Normal, encouragement, and click dialogue can reflect the selected personality.
- Work/break/leave warnings retain priority and are not weakened by personality.
- Character short-click still opens detail and leaves a reaction line for the compact view.
- Time-of-day dialogue: morning / lunch / afternoon / evening / late.
- Rare dialogue / easter eggs: 4% target chance plus minimum 12 normal selections between rare lines.
- Habit reactions use existing away/continuous-use state only.
- Custom dialogue: newline-separated user lines, bounded and mixed into normal dialogue only.
- Daily temperament: date-stable calm / bright / focused, lightweight and non-persistent.

## Non-negotiable constraints

- Do not turn personality into affinity, level, score, or reward systems unless explicitly requested later.
- Do not allow custom/rare/daily dialogue to replace break warnings, away state, leave-work warnings, or hard-stop messages.
- Preserve Phase 1 drag/hotkey/position behavior.
- Preserve Phase 3 visible-alpha compact layout and transparent click-through behavior.
- Preserve Phase 4 image-set/preview behavior and approved canonical assets.

## Validation

- Dialogue/unit tests cover personality, time buckets, rare minimum gap/chance, custom dialogue, habit priority, and daily temperament stability/chance.
- Daily temperament implementation commit: `413198b87f68966b5043c038808f246611b3f0c2`.
- Phase 5 mid-checkpoint Windows build/smoke previously passed after personality/custom-dialogue integration.
- Final branch tests/build/smoke should be taken from the clean closeout HEAD before Phase 6 changes.
'''
(ROOT / "PHASE5_HANDOFF.md").write_text(handoff, encoding="utf-8")

phase6 = '''# Phase 6 Handoff — Work / Break Behavior

## Status

ACTIVE / NOT YET IMPLEMENTED BEYOND EXISTING BASELINE.

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
'''
(ROOT / "PHASE6_HANDOFF.md").write_text(phase6, encoding="utf-8")
print("Phase 5 closed and Phase 6 handoff created")
