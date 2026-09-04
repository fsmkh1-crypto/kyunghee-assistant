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

Root-level `README.md`, `atlas_manifest.json`, and compatibility metadata stay in `assets/`.

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

Legacy compatibility files are kept in the closest matching role folder. `asset_manager.py` resolves the role-folder path first and still accepts the old flat layout as a fallback for older external packs.

## Naming rule for future additions

Prefer `<role>_01.png`, `<role>_02.png`, etc. Add a short semantic suffix only when useful, e.g. `cheer_thumbsup_01.png`.

Full-body artwork must preserve aspect ratio and visible legs. Future poses should preserve the same canonical identity direction as the approved profile/master assets.
