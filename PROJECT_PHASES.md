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

### Status: FUNCTIONALLY IMPLEMENTED; FINAL SPACING VISUAL CONFIRMATION PENDING

Implemented:
- `widget_scale` range expanded to 80–200%.
- `show_time`, `show_status`, `show_message` settings.
- Live scale preview and live visibility toggles.
- Character rerender at preview scale.
- Settings return preserves preview; save persists it.
- Typography no longer scales with widget scale. Time/status/message text sizes remain controlled by their own settings.
- Compact transparent canvas has a generous minimum size so even small character scales have room for time/status/message.
- Canvas expands further for large character scales.
- Kyunghee image drag works even when time/status are hidden; short click still opens detail.
- Message stays clickable and cycles dialogue.
- Transparent color-key layout preserved; empty transparent areas currently click through to applications behind the widget.

### Layout evolution and latest rule
Earlier scale-dependent offsets caused excessive empty space between the clock/status group and Kyunghee, especially at 80/140/200%.

The latest implementation replaces that with a fixed-cluster layout:
- Clock/status + Kyunghee are treated as one visible horizontal cluster.
- Their edge-to-edge horizontal gap is fixed at about 30 px across all widget scales.
- Clock/status follows Kyunghee vertically instead of staying pinned to the canvas top-left.
- Message is centered directly under Kyunghee.
- Character-to-message relationship is fixed instead of increasing with scale.
- The transparent canvas may remain large, but visible elements should not drift apart as scale grows.

Latest source commit for this layout:
- `2f721b996c26402e01c6f2233a7df5b4df3090d1` — `Keep timer UI clustered across scales`

Latest packaging trigger commit:
- `9d8f8a22387b240ba2235f9ea55e0a4ce4603386` — `Build fixed-cluster Phase 3 test package`

Latest Windows test package:
- Artifact name: `kyunghee-timer-phase3-final-test`
- Build workflow run: `33842885602`
- Build/tests/smoke: PASS

### Remaining Phase 3 item
- One real-Windows visual confirmation of the fixed-cluster build at roughly 80%, 140%, and 200%.
- If spacing still feels off, tune the single fixed cluster gap rather than reintroducing scale-dependent gap tables.
- Do not redesign the transparent-canvas model unless necessary; the click-through empty area is beneficial.

---

## Phase 4 — Image system

### Goal
Make situation-based Kyunghee artwork flexible without replacing the approved canonical assets.

### Status: NEXT PHASE / NOT STARTED

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
2. Inspect PR #3 and branch `ui/dark-kyunghee-redesign`, not `main`.
3. Treat `desktop_compact.py` as the current desktop entrypoint.
4. Confirm the current branch HEAD before editing.
5. Do not replace approved PNG assets.
6. Preserve Phase 1 drag/hotkey/position behavior.
7. Preserve the transparent color-key model and empty-area click-through behavior unless a regression requires otherwise.
8. Phase 3 uses a fixed visible cluster; do not reintroduce scale-dependent clock/character spacing tables without a strong reason.
9. Phase 4 is the next implementation phase.
10. After risky Windows-specific changes, run tests/build/smoke; request real-device testing only when CI cannot validate the visual behavior.

## Last known user feedback

- Phase 1 real-world behavior passed.
- Phase 2 visual baseline accepted; user wanted user-adjustable scale.
- Phase 3 live controls now work and scale range is 80–200%.
- Large transparent canvas is acceptable because empty transparent areas currently click through to the app behind it; user explicitly likes this behavior.
- Previous Phase 3 layouts left clock/status too far from Kyunghee at 80/140/200%.
- Latest code changed to a fixed-cluster model with one constant clock-to-character gap and message directly under Kyunghee.
- Final visual confirmation of that latest fixed-cluster build is the only outstanding Phase 3 check.

This file should be updated whenever a phase is completed, materially changed, or a new real-world issue is discovered.
