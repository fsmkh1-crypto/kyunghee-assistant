# Kyunghee Timer Project Phases

This document is the single handoff/status reference for the current desktop timer work.

## Canonical branch and entrypoint

- Repository: `fsmkh1-crypto/kyunghee-assistant`
- Working branch: `ui/dark-kyunghee-redesign`
- Pull request: #3 `UI: dark Kyunghee timer redesign`
- Desktop entrypoint: `desktop_compact.py`
- `main` is obsolete for the current desktop UI and must not be used for review or implementation unless explicitly requested.
- Approved character PNG assets in `assets/` are canonical and must not be regenerated or replaced.
- Pretendard is expected to be installed on the user's PC. Do not bundle font files.

## Product/UI decisions already fixed

- Frameless transparent Windows desktop widget.
- No outer panel, titlebar, timer background, or message bubble on the compact screen.
- Main compact view shows Kyunghee art plus optional time/status/message and a tiny emergency `×`.
- Time/status/message backgrounds stay transparent.
- Time is green; message is rose/pink; Pretendard Regular only.
- Kyunghee image click opens detail.
- Message click changes dialogue.
- Kyunghee image drag moves the window; short click still opens detail.
- Timer/status remain drag surfaces when visible.
- Emergency global hide/show hotkey: `Ctrl+Shift+H`.
- Do not use global Esc. Local Esc and `×` may hide the app.
- User-controlled always-on-top.
- Empty transparent areas currently allow clicks to pass through to the window behind on Windows. This emerged from the transparent color-key behavior and is now a desirable behavior. Preserve it unless a regression forces reconsideration.

---

## Phase 1 — Stability

### Status: COMPLETE / REAL-WORLD TEST PASSED

Implemented and validated:
- Compact startup entrypoint.
- Detail/settings drag support.
- Multi-monitor-aware position clamping and off-screen recovery.
- Window position persistence, including negative monitor coordinates.
- Global `Ctrl+Shift+H` hide/show hotkey.
- Custom image import into the app-owned data folder.
- Missing custom image fallback.
- Custom image dimension guard.
- Field-level settings recovery.
- Windows-only compact entrypoint guard.
- Pretendard availability logging.
- Correct top-level HWND use for Win32 drag.

Ubuntu tests, Windows tests/build/smoke tests, and real Windows drag/window testing passed.

---

## Phase 2 — Display quality / Windows display behavior

### Status: CODE INTEGRATED; VISUAL BASELINE ACCEPTED

Implemented:
- Premultiplied-alpha-safe image resize path.
- Alpha threshold helper, current threshold around 112.
- Character image cache/invalidation.
- Reduced unnecessary OutlinedText geometry recalculation.
- Per-monitor DPI awareness before Tk creation.
- Fullscreen/presentation detection with notification suppression.
- Topmost restoration after fullscreen/presentation state ends.

Deferred tuning only if visual artifacts reappear:
- Compare alpha threshold 96/112/128.
- Reduce 8-way text outline if still too heavy.
- Mixed-DPI dual-monitor visual comparison.

---

## Phase 3 — Scale / visibility / compact layout

### Goal
Let the user resize the compact widget from 80–200%, selectively hide time/status/message, and keep the visible UI visually grouped without overlap.

### Status: COMPLETE / REAL-WORLD VISUAL PASS

Implemented and validated:
- `widget_scale` range 80–200%.
- `show_time`, `show_status`, `show_message` settings.
- Live scale preview and live visibility toggles.
- Character rerender at preview scale.
- Settings return preserves preview; save persists it.
- Typography is independent from widget scale. Time/status/message text sizes remain controlled by their own settings.
- Compact transparent canvas has a generous minimum size so small character scales still have room for time/status/message.
- Canvas expands further for large character scales.
- Kyunghee image drag works even when time/status are hidden; short click still opens detail.
- Message remains clickable and cycles dialogue.
- Transparent color-key layout preserved; empty transparent areas currently click through to applications behind the widget.

### Final layout rule
Earlier scale-dependent offsets and whole-PNG-box spacing left the clock/status group visually too far from Kyunghee at 80/140/200%.

The final layout therefore uses the visible character silhouette instead of the PNG canvas box:
- Clock/status + Kyunghee are treated as one visible cluster.
- Clock placement is derived from the actual visible alpha bounds of the rendered Kyunghee image, not the image's transparent outer rectangle.
- The visual gap between the clock/status group and Kyunghee is kept small and effectively fixed across scales (about 12 px target).
- Clock/status follows the character vertically instead of staying pinned to the canvas top-left.
- Message is centered under Kyunghee.
- Character-to-message spacing stays visually stable rather than increasing with scale.
- The transparent canvas may remain large, but visible elements must not drift apart as scale grows.

Latest Phase 3 source commit:
- `f123574fdbeb0008f2c65b09d05fc0098b686049` — `Align clock to visible character silhouette`

Latest Phase 3 packaging trigger commit:
- `c597157e6bec50c431104a92344b00fe786a9a30` — `Build visible-alpha cluster Phase 3 test package`

Latest Windows validation:
- Workflow: `Build Phase 3 final test`
- Run: `33845865572`
- Compile/tests: PASS
- Windows build: PASS
- Smoke test: PASS
- Artifact: `kyunghee-timer-phase3-final-test`
- User visually checked 80%, 140%, and 200% screenshots and accepted the result as good enough to close Phase 3.

Do not rework Phase 3 layout during Phase 4 unless a real regression appears.

---

## Phase 4 — Image system

### Goal
Make situation-based Kyunghee artwork flexible without replacing the approved canonical assets.

### Status: NEXT PHASE / READY TO START

Planned priority:
1. Multiple images per role/situation with random selection.
2. Folder/set support.
3. Fit/crop/alignment controls.
4. Image preview in settings.
5. Robust cache/invalidation for sets and previews.
6. Keep app-owned imported copies as the default storage model.

Important constraints:
- Do not regenerate or replace approved PNG masters in `assets/`.
- Preserve existing single-image custom import/fallback behavior while extending it.
- Do not break Phase 1 drag/hotkey/position behavior.
- Do not break Phase 3 scale/visibility/transparent click-through behavior.
- Preserve visible-alpha-based clock/character clustering unless a real regression requires change.

---

## Phase 5 — Personality / fun behaviors

### Status: NOT STARTED

Priority order:
1. Dialogue personality presets.
2. Rare dialogue / easter eggs.
3. Character click reactions.
4. Time-of-day reactions.
5. Streak/habit reactions.
6. Custom dialogue.
7. Daily/random temperament.

Avoid turning the app into a heavy game system.

---

## Phase 6 — Work/break behavior

### Status: NOT STARTED

Planned:
- Configurable break intervals.
- Snooze behavior.
- “Stop reminders for today”.
- Work start/end policy refinement.
- Manual/automatic away behavior.
- Fullscreen/presentation deferral integration.
- Optional Pomodoro mode later.

Requires real-world multi-day usage testing before completion.

---

## Phase 7 — Stats

### Status: NOT STARTED

Planned:
- 7-day summary.
- Personal records / streak-style summaries where useful.
- Dialogue reactions to stats.
- CSV export only later if still useful.

Data correctness is more important than visual complexity.

---

## Explicitly deferred / not now

- WPF rewrite.
- Heavy game/leveling systems.
- Large sound system.
- Built-in image editor.
- CSV export in early phases.
- Unnecessary pixel-perfect layout preset complexity.

---

## New-conversation / reviewer checklist

Before changing code:
1. Read this file first.
2. Read `PHASE4_HANDOFF.md`.
3. Inspect PR #3 and branch `ui/dark-kyunghee-redesign`, not `main`.
4. Treat `desktop_compact.py` as the current desktop entrypoint.
5. Confirm the current branch HEAD before editing.
6. Do not replace approved PNG assets.
7. Preserve Phase 1 drag/hotkey/position behavior.
8. Preserve the transparent color-key model and empty-area click-through behavior unless a regression requires otherwise.
9. Phase 3 is complete; preserve its visible-alpha cluster layout instead of redesigning it.
10. Phase 4 is the next implementation phase.
11. After risky Windows-specific changes, run tests/build/smoke; request real-device testing only when CI cannot validate the visual behavior.

## Last known user feedback

- Phase 1 real-world behavior passed.
- Phase 2 visual baseline accepted; user wanted user-adjustable scale.
- Phase 3 live controls, 80–200% scale, independent typography, visibility toggles, character click/drag behavior, and transparent click-through behavior all work.
- User explicitly likes that empty transparent areas allow clicks to reach applications behind the widget.
- Final Phase 3 layout uses visible-alpha silhouette bounds so clock/status stays visually close to Kyunghee at 80/140/200%.
- User reviewed the final 80/140/200 screenshots and approved moving on to Phase 4.

This file should be updated whenever a phase is completed, materially changed, or a new real-world issue is discovered.
