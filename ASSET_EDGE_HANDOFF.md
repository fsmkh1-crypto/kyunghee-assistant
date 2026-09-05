# Asset Edge Quality Handoff

Status: DISCUSSION / DIAGNOSIS NEXT — DO NOT MODIFY RUNTIME OR ASSETS WITHOUT EXPLICIT USER APPROVAL

Repository: `fsmkh1-crypto/kyunghee-assistant`
Branch: `ui/dark-kyunghee-redesign`
Head before this handoff commit: `605a946deb20d275e1b9966b07ce553c73aa5051`
PR: #3 (`UI: dark Kyunghee timer redesign`)

## User intent

The user wants the built-in character assets to look less rough around the silhouette/transparent edge in the real Windows app. Message/dialogue redesign is currently paused; the active topic is asset edge quality.

The user explicitly asked to discuss/diagnose before further implementation. Do **not** interpret a question such as "어떻게 할까" or "차이가 있냐" as authorization to edit code. Only make runtime/asset changes after a clear instruction such as "시작해", "진행해", or an equivalent explicit approval.

## Important correction from the previous session

A conservative runtime smoothing experiment was implemented too early. It is currently present on this branch:

- `image_render.py`: `threshold_alpha(..., smooth_radius=...)`
- `desktop_compact.py`: built-in assets use `BUILTIN_ALPHA_SMOOTH_RADIUS = 0.35`; user-supplied images remain at `0.0`
- `tests/test_image_render.py`: coverage for smoothing

The measured result was numerically safe but visually very small. The assistant's visual judgment after comparing before/after was: **the difference is barely noticeable at normal app size and does not solve the user's rough-edge complaint.**

Therefore this `0.35` runtime smoothing must **not** be treated as an accepted final solution. Recommended discussion point: revert only this low-value runtime smoothing while keeping the diagnostic tooling, but do not perform that revert until the user explicitly approves it.

## Diagnostic tooling already added

The following developer-only quality lab exists and is useful for further diagnosis:

- `tools/asset_display_lab.py`
- `tools/test_asset_display_lab.py`
- `.github/workflows/asset-quality-lab.yml`
- `.asset_display_lab/` is ignored via `.gitignore`

The lab evaluated all 50 numbered built-in assets at 80/100/140/200% scales. The original threshold `112` remained the safest baseline. The `0.35` smoothing experiment produced only a very small silhouette change and no topology changes, but the visual improvement was not meaningful enough.

The lab's automated review-priority list from that run was:

1. `away_02`
2. `leave_02`
3. `away_03`
4. `default_02`
5. `cheer_04`
6. `away_05`
7. `profile_05`
8. `cheer_05`
9. `cheer_02`
10. `cheer_03`
11. `cheer_01`
12. `warning_05`

These are **review candidates, not automatic defect verdicts**.

## Recommended next decision path

Do not start by reprocessing all 50 PNGs. First determine where the visible roughness comes from.

1. Pick a small representative sample (roughly 6–10 assets, including hair, legs/feet, clothing edges, and props).
2. Render the exact same PNGs at actual app display sizes in two modes:
   - normal true-alpha compositing on a neutral/dark background;
   - the current Tk/Windows binary color-key output.
3. Compare them visually:
   - true-alpha clean + app output rough => renderer/color-key limitation is dominant;
   - true-alpha already rough => PNG edge/matte is dominant;
   - both rough => fix PNG edge quality first, then consider renderer work.
4. Only after that diagnosis choose one path:
   - **Asset path:** repair only the genuinely bad PNGs (matte cleanup, edge RGB bleed, tiny spur/notch cleanup, contour regularization), preserving pose/layout/character exactly.
   - **Renderer path:** make a small proof-of-concept for per-pixel alpha (for example a Windows layered-window approach) before considering any larger UI migration.

Do not strengthen Gaussian blur/threshold smoothing merely because the metrics improve; the previous experiment showed that numerical improvement did not translate into meaningful visual improvement.

## Duplicate and set-integrity protection is already implemented

New asset-sheet imports already have duplicate protection in `tools/import_asset_sheet.py` and `assets/asset_index.json`:

- duplicate source sheet SHA-256 is rejected by default;
- exact duplicate output PNGs are detected/rejected by default;
- near-identical **same-role** outputs are compared using silhouette, luminance, and appearance signatures and rejected by default pending review;
- duplicate candidates are marked in the generated contact sheet;
- intentional exceptions require explicit review flags (`--allow-duplicate-source`, `--allow-duplicate`, `--allow-near-duplicate`).

Runtime set integrity is also covered by tests: numbered assets are selected as one complete coherent set, rather than mixing unrelated role images from different built-in sets.

Do not replace this with a second duplicate system unless a concrete gap is found.

## Asset contract — preserve

There are 5 numbered built-in sets (01–05), 10 roles per set, 50 numbered assets total.

Role order:
1. default
2. cheer
3. rest
4. away
5. warning
6. leave
7. stats
8. settings
9. alert
10. profile

Do not overwrite canonical fallback masters without explicit user request:

- `assets/default/main_kyunghee.png`
- `assets/cheer/focus_cheer_kyunghee.png`
- `assets/rest/rest_suggest_kyunghee.png`
- `assets/away/away_kyunghee.png`
- `assets/warning/warning_kyunghee.png`
- `assets/leave/leave_work_kyunghee.png`
- `assets/stats/stats_kyunghee.png`
- `assets/settings/settings_kyunghee.png`
- `assets/alert/alert_kyunghee.png`
- `assets/profile/profile_kyunghee.png`

Image priority remains:
`user custom > built-in selected complete set > canonical fallback`.

If individual PNGs are later repaired, preserve the original pose, crop intent, dimensions/aspect behavior, detached props, and role/set numbering. This is edge repair, not character redesign.

## Current validation state before this handoff commit

On the then-current HEAD `605a946deb20d275e1b9966b07ce553c73aa5051`:

- Ubuntu unit/assets tests: success
- Windows unit/assets tests: success
- Windows PyInstaller build: success
- Windows smoke test: success
- Desktop Package build + packaged-app smoke: success

`desktop-package.yml` also accepts manual dispatch so a Windows test package can be generated on demand.

## Temporary implementation files already cleaned up

The one-shot smoothing application workflow/script used during the prior experiment were removed. Do not recreate them unless there is a specific need.

## Files to read before continuing

Read these first in the new session:

1. `ASSET_EDGE_HANDOFF.md` (this file)
2. `PROJECT_PHASES.md`
3. `PHASE7_HANDOFF.md`
4. `PHASE6_HANDOFF.md` (validation reference only)
5. PR #3 metadata/diff as needed
6. Current branch HEAD and any commits made after this handoff

Then report the current state in a few lines and continue **discussion/diagnosis only** unless the user explicitly authorizes implementation.
