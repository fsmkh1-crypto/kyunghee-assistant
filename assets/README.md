# Character asset contract

The approved Kyunghee assets are organized by user-facing role. Do not regenerate or replace approved masters without explicit instruction.

## Folder layout

- `default/` — normal / playful
- `cheer/` — focus encouragement / cute cheer
- `rest/` — break suggestion
- `away/` — away state
- `warning/` — worry / nag / late-work warnings
- `leave/` — leave-work / praise
- `stats/` — stats screen
- `settings/` — settings screen
- `alert/` — alert/toast artwork
- `profile/` — profile / identity face

Root-level `README.md`, `atlas_manifest.json`, `asset_index.json`, and compatibility metadata stay in `assets/`.

## Approved masters

- `default/main_kyunghee.png`
- `cheer/focus_cheer_kyunghee.png`
- `rest/rest_suggest_kyunghee.png`
- `away/away_kyunghee.png`
- `warning/warning_kyunghee.png`
- `leave/leave_work_kyunghee.png`
- `stats/stats_kyunghee.png`
- `settings/settings_kyunghee.png`
- `alert/alert_kyunghee.png`
- `profile/profile_kyunghee.png`

Legacy compatibility files are kept in the closest matching role folder.

## Numbered built-in sets

Numbered files such as `default_01.png`, `cheer_01.png`, ... `profile_01.png` are not independent random variants. Files with the same number form one complete visual set.

At runtime `asset_manager.py` scans for set numbers that exist for all ten folders, chooses one complete set once per process, and resolves every role from that same set number. This prevents mixed outfits such as `default_05` with `rest_03`.

Runtime priority is:

1. user-imported/custom image set handled by the desktop UI,
2. one coherent built-in numbered set,
3. approved canonical/legacy master fallback.

A numbered set is ignored as a runtime choice if any of the ten role files is missing.

## Naming rule for future additions

Use `<role>_01.png`, `<role>_02.png`, etc. Keep the same number across all ten roles. Add a semantic suffix only for non-standard compatibility assets.

Full-body artwork must preserve aspect ratio and visible legs. Future poses should preserve the same canonical identity direction as the approved profile/master assets.

## Duplicate semantics

`assets/asset_index.json` tracks installed numbered assets. Identical source bytes or identical output bytes are duplicates. A similar pose is **not** a duplicate when clothing, colour, pattern, or other visible appearance differs. Near-duplicate warnings therefore require both pose similarity and close normalized appearance.
