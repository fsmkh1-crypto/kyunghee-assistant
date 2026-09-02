# Claude review status

Current line: `0.4.0-alpha`

## Closed from the previous reviews

- manual-away self-cancel from the click that starts it
- sleep/wake gap being counted as active
- manual-away sleep gap being counted as active
- break reminder getting permanently disarmed after another toast replaces it
- stale session resurrection after long app downtime
- midnight daily/session separation
- duplicate-instance state-file races
- toast timer closing a newer toast
- tray UI queue dying permanently after one callback exception
- auto-away `복귀` button starting manual-away instead of returning
- dialogue rotation regression
- idle-candidate persistence across short crash/restart
- startup reset/rollover ordering
- leave-work mode still offering `5분 더`
- monotonic return-duration timing
- manual/auto classification across long manual-away gaps
- 64-bit mutex handle declaration
- finalized runtime character assets committed and role-mapped
- `오늘 기록` changed from a toast into a live second page

## Current workday policy

- usual arrival around 08:40
- wind-down from 17:00
- leave-work mode from 17:30
- stronger leave prompts from 18:00
- late-work nagging from 18:30
- hard-stop prompt at 9 hours of actual active use

After 17:30 the UI must not offer a button or message that encourages extending work.

## Current idle policy

No input for less than five minutes is provisionally counted as active. If the five-minute threshold is reached, the entire no-input candidate interval is retroactively reclassified as away.

## Current UI / assets

- page 1: current continuous active use, time to next break, live character image, dialogue, away button
- page 2: today active time, away time, away count, longest continuous use, utilization, cheer image
- character roles: default, playful, cheer, cute_cheer, worry, nag, praise, master_face
- runtime assets are committed as compact WebP plus a PNG master face
- asset resolution/opening is covered by CI tests
- CI runs on both Ubuntu and Windows with source compilation and unit tests

## Review focus for the next pass

Please read current `main` and look specifically for regressions around:

1. manual/auto away transitions and `away_count`
2. midnight while a timer tick is active
3. crash/restart within and outside the 60-second continuity tolerance
4. long sleep gaps with and without a wake input
5. repeated break reminders and leave-work snooze suppression
6. tray queue exception recovery
7. state schema v6 migration/coercion
8. two-page Tk UI lifecycle, image references, page switching and live stats refresh
9. WebP/PNG asset loading and tray image handling on Windows
10. privacy: last-input timing metadata only

Report issues as: title, reproduction, actual, expected, severity, minimal fix.
