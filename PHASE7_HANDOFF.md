# Phase 7 Handoff — Recent Stats

## Status

ACTIVE / 7-DAY HISTORY FOUNDATION AND SUMMARY UI INTEGRATED.

## Implemented

- State schema 8 keeps up to 30 archived daily records.
- A finished day is archived at local-day rollover before daily counters reset.
- Existing schema 7 state files continue to load with an empty history.
- Corrupt or malformed history entries are ignored without losing the current day/session.
- Recent-stat helpers build a calendar-aligned 7-day window and fill missing days with zero records.
- Summary metrics include 7-day active time, tracked-day average, active/away ratio, total away count, longest continuous focus, and best active day.
- The desktop detail screen shows the 7-day total, tracked-day average, and best day alongside the existing today metrics.
- Kyunghee gives a lightweight recent-stats reaction without adding levels, scores, or a heavy gamification system.

## Next checks

- Use the app across several day rollovers and verify archived totals against real usage.
- Tune wording/spacing only if the compact detail screen feels crowded in Windows.
- Consider streak-style wording later only if it adds useful information; do not invent arbitrary productivity targets.
- CSV export remains deferred unless the user actually needs it.

## Data rules

- Historical collection begins with schema 8; daily records from before this rollout were never stored and cannot be reconstructed.
- Current-day data overrides any same-day archived entry.
- “기록일 평균” averages only days that contain recorded activity; missing calendar days are not treated as fake workdays.
- 7-day totals still cover the full calendar window, including zero days.
- Data correctness has priority over visual complexity.
