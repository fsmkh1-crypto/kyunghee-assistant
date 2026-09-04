# Asset batch import review — 2026-09-04

Source: six user-uploaded ZIP archives supplied together.

## Summary

- 60 PNG files received.
- 10 files are exact duplicates (`kyunghee_timer_assets_10png (1).zip` duplicates `kyunghee_timer_assets_10png.zip`).
- 50 unique images remain: 5 variants for each of the 10 user-facing roles.
- Two 900x1200 / 512x512 sets are clean high-resolution runtime candidates (20 images total).
- Three split-sheet-derived sets are retained as references only because they are lower-resolution and/or contain crop-edge remnants or embedded labels.

## Role mapping

| Source name | Role folder |
|---|---|
| `01_normal.png` | `default/` |
| `02_focus_cheer.png` | `cheer/` |
| `03_break_suggestion.png` | `rest/` |
| `04_away.png` | `away/` |
| `05_warning.png` | `warning/` |
| `06_leave_work.png` | `leave/` |
| `07_statistics.png` | `stats/` |
| `08_settings.png` | `settings/` |
| `09_notification.png` | `alert/` |
| `10_profile.png` | `profile/` |

## Source-set assessment

- `kyunghee_timer_assets_10png.zip` — high-resolution candidate set A.
- `kyunghee_timer_assets_first_sheet_10png.zip` — high-resolution candidate set B.
- `kyunghee_timer_assets_10png (1).zip` — exact duplicate of candidate set A; do not import twice.
- `kyunghee_split_wide_050844_2_10png.zip` — lower-resolution split set; reference only.
- `kyunghee_split_labeled_sheet_10png.zip` — contains labels/text baked into images; reference only.
- `kyunghee_split_050844_10png.zip` — lower-resolution split/crop set with edge remnants; reference only.

## Naming for runtime candidates

For future bundled variants use `<role>_01.png`, `<role>_02.png`, etc. Existing approved canonical masters remain untouched and keep priority.

## Preservation

Original uploads are retained in the user's uploaded-file library. A deduplicated classified archive with all 50 unique images was also created during this review.
