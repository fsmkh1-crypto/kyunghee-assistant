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
- Time is green; message is rose/pink; Pretendard Regular only.
- Kyunghee image click opens detail.
- Message click changes dialogue.
- Timer/status are drag surfaces when visible.
- Emergency global hide/show hotkey: `Ctrl+Shift+H`.
- Do not use global Esc. Local Esc and `×` may hide the app.
- User-controlled always-on-top.

---

## Phase 1 — Stability

### Goal
Make the current Tkinter app safe and reliable enough for everyday Windows use.

### Status: COMPLETE / REAL-WORLD TEST PASSED

Implemented:
- Startup command fixed to use the compact entrypoint.
- Detail/settings drag support.
- Multi-monitor-aware position clamping and off-screen recovery.
- Window position persistence, including negative monitor coordinates.
- Global `Ctrl+Shift+H` hide/show hotkey.
- Custom image import into the app-owned data folder.
- Missing custom image fallback.
- Custom image dimension guard.
- Field-level settings recovery instead of resetting the whole settings file.
- Windows-only guard for compact entrypoint.
- Pretendard availability logging.
- Fixed Win32 drag regression caused by using the child HWND instead of the real top-level wrapper HWND.

Validation:
- Ubuntu tests passed.
- Windows tests/build/smoke tests passed.
- User tested drag and said all Phase 1 behavior worked correctly.

No further Phase 1 action unless a regression appears.

---

## Phase 2 — Display quality / Windows display behavior

### Goal
Improve character edge quality, DPI behavior, and fullscreen/presentation coexistence.

### Status: CODE INTEGRATED; VISUAL BASELINE ACCEPTED ENOUGH TO CONTINUE

Implemented:
- Alpha-safe image resize path using premultiplied-alpha handling.
- Binary alpha threshold helper, current threshold around 112.
- Character image cache and invalidation.
- Reduced unnecessary OutlinedText geometry recalculation.
- Per-monitor DPI-awareness helper, enabled before Tk creation.
- Fullscreen/presentation detection with `SHQueryUserNotificationState`.
- During suppressed state: topmost disabled and toast/break notifications suppressed.
- Topmost restored afterward according to user preference.

Observed during real-world test:
- App appeared smaller after DPI-awareness changes. This is not treated as a Phase 2 rendering failure; user requested a user-controlled widget scale instead.

Remaining Phase 2 checks that can be revisited later if needed:
- Fine-tune alpha threshold on multiple backgrounds (96/112/128 comparison).
- Reduce 8-way text outline to 4 cardinal offsets if text still looks too heavy.
- Mixed-DPI dual-monitor visual comparison.

Do not block later phases on these unless visual artifacts reappear.

---

## Phase 3 — Settings structure / scale / visibility controls

### Goal
Let the user control compact-widget size and selectively hide time/status/message while keeping the widget movable.

### Status: IN PROGRESS — CURRENT ACTIVE BUGFIX AREA

Already added:
- `widget_scale` setting, intended range 80–140%.
- Default scale raised to about 110% to offset the smaller post-DPI appearance.
- `show_time`, `show_status`, `show_message` settings.
- Settings UI with scale slider and three visibility toggles.
- Invisible top drag strip so the compact widget remains movable even when time/status are hidden.
- Scaling intended to affect compact window, Kyunghee image, time/status/message fonts, wrap width, positions, and `×`.
- Schema/tests updated for the new display preferences.

### Known real-world bug
The first Phase 3 test build did not visibly react when the user moved the slider or toggled time/status/message. The controls existed but live application behavior was incomplete/broken.

### Required fix before Phase 3 can be marked complete
- Slider must visibly resize the compact widget while dragging, not only after a later save/restart.
- Character image must be rerendered at the preview scale.
- Time/status/message toggles must immediately show/hide the corresponding widgets.
- Returning from settings to timer must preserve the preview state.
- `Save Settings` must persist the same state for next launch.
- Cancel/back behavior should be intentionally defined: either keep preview and save explicitly, or revert unsaved preview. Current preferred behavior: live preview, explicit save for persistence.
- Verify invisible drag strip still works when time and status are both hidden.

### Immediate next action
Finish and test the live-preview wiring for the slider and visibility toggles. Do not start Phase 4 until this passes one short Windows real-device test.

---

## Phase 4 — Image system

### Goal
Make situation-based Kyunghee artwork flexible without replacing the approved canonical assets.

### Status: NOT STARTED

Planned:
- Multiple images per situation/role.
- Random selection from role pools.
- Folder-based image sets.
- Fit/crop/alignment options.
- Image preview in settings.
- Robust cache/invalidation.
- App-owned imported image copies remain the default storage model.

Priority inside Phase 4:
1. Multiple images per role with random selection.
2. Folder/set support.
3. Fit/crop/alignment controls.
4. Preview and cache refinements.

Do not regenerate approved PNG masters.

---

## Phase 5 — Personality / fun behaviors

### Goal
Make Kyunghee feel less static and more like a lightweight desktop companion.

### Status: NOT STARTED

Priority order already agreed:
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

### Goal
Turn the timer into a more useful work companion without excessive interruption.

### Status: NOT STARTED

Planned:
- Configurable break intervals.
- Snooze behavior.
- “Stop reminders for today”.
- Work start/end policy refinement.
- Manual/automatic away behavior.
- Fullscreen/presentation deferral integration.
- Optional Pomodoro mode later, not mandatory for first completion.

Requires real-world multi-day usage testing before being called finished.

---

## Phase 7 — Stats

### Goal
Provide useful lightweight history without overbuilding analytics.

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
- Pixel-free or fully fluid layout architecture.
- Complex layout preset system.
- Large sound system.
- Built-in image editor.
- CSV export in early phases.
- Heavy leveling/game mechanics.

---

## Review checklist for a new conversation or external reviewer

Before changing code:
1. Read this file.
2. Inspect PR #3 and branch `ui/dark-kyunghee-redesign`, not `main`.
3. Treat `desktop_compact.py` as the current desktop entrypoint.
4. Confirm current branch head before editing.
5. Do not replace approved PNG assets.
6. Preserve the Phase 1 drag/hotkey/position behavior that already passed real-device testing.
7. Current highest-priority task is the Phase 3 live scale/toggle bug.
8. After each risky Windows-specific change, run tests/build/smoke, but request real-device testing only when the behavior cannot be validated in CI.

## Last known user feedback

- Phase 1: real-world test passed; drag and window behavior worked.
- Phase 2: app looked smaller after DPI work; user requested user-adjustable scale.
- Phase 3 first test: scale slider did not change visible size, and time/status/message ON/OFF did not work visibly.

This file should be updated whenever a phase is completed, materially changed, or a new real-world issue is discovered.
