from pathlib import Path

p = Path('PROJECT_PHASES.md')
t = p.read_text(encoding='utf-8')
old = '''### Status: IN PROGRESS / IMAGE-SET RUNTIME INTEGRATED

Implemented so far:
- App-owned multi-image sets per role/situation.
- Multiple-file and folder import.
- Random image selection when a role is re-entered, with stable display while the role remains active.
- Fit/crop plus 9-way alignment controls.
- Legacy single-image custom import preserved as fallback, followed by canonical approved assets.
- Image-set cache/invalidation integrated into the compact runtime.
- Ubuntu tests and Windows compile/tests/build/smoke passed after runtime integration.

Remaining priority:
1. Image preview in settings.
2. Preview-specific cache/invalidation polish.
3. Real-device visual check of the expanded image settings UI.
4. Keep app-owned imported copies as the default storage model.
'''
new = '''### Status: COMPLETE / REAL-WORLD SETTINGS UI PASS

Implemented and validated:
- App-owned multi-image sets per role/situation.
- Multiple-file and folder import.
- Random image selection when a role is re-entered, with stable display while the role remains active.
- Fit/crop plus 9-way alignment controls.
- Legacy single-image custom import preserved as fallback, followed by canonical approved assets.
- Image-set cache/invalidation integrated into the compact runtime.
- Settings image preview with role selection and previous/next navigation across image sets.
- Preview reflects fit/crop and 9-way alignment changes without disturbing runtime random selection.
- Preview-specific cache/invalidation is separate from runtime character caching.
- App-owned imported copies remain the storage model.
- Settings page mouse-wheel scrolling works across the panel, including when the pointer is over controls/preview widgets.
- Ubuntu tests and Windows compile/tests/build/smoke passed after final Phase 4 changes.
- User visually accepted the expanded settings/preview UI and identified the mouse-wheel regression; the wheel fix was then integrated and Windows build/smoke passed.
'''
if t.count(old) != 1:
    raise SystemExit(f'phase4 block match count={t.count(old)}')
t = t.replace(old, new, 1)
t = t.replace('''### Status: NOT STARTED

Priority order:
1. Dialogue personality presets.
2. Rare dialogue / easter eggs.
3. Character click reactions.
4. Time-of-day reactions.
5. Streak/habit reactions.
6. Custom dialogue.
7. Daily/random temperament.
''', '''### Status: IN PROGRESS / PERSONALITY FOUNDATION INTEGRATED

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
''', 1)
t = t.replace('2. Read `PHASE4_HANDOFF.md`.', '2. Read `PHASE5_HANDOFF.md` (Phase 4 handoff is historical).', 1)
t = t.replace('10. Phase 4 is in progress; image-set runtime integration is complete and settings preview is next.', '10. Phase 4 is complete; preserve the image-set/preview system. Phase 5 is active.', 1)
t = t.replace('- User reviewed the final 80/140/200 screenshots and approved moving on to Phase 4.\n', '- User reviewed the final 80/140/200 screenshots and approved moving on to Phase 4.\n- Phase 4 settings preview UI was accepted in real Windows use. A missing mouse-wheel binding was found and fixed; Phase 4 is closed.\n- Phase 5 personality foundation is now the active workstream.\n', 1)
p.write_text(t, encoding='utf-8')
