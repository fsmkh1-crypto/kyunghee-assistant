# Character asset contract

The UI uses the finalized Kyunghee character set through `asset_manager.py`.

## Committed runtime files

The repository now contains the full runtime set:

- `default_full.webp` — normal main pose
- `playful.webp` — compact playful/default dialogue
- `cheer_full.webp` — stats / fighting pose
- `cheer.webp` — compact cheer
- `cute_cheer.webp` — return / light praise
- `nag.webp` — repeated snooze / late-work / hard-stop
- `worry.webp` — first snooze / wind-down / break reminder
- `praise.webp` — leave-mode close-out
- `master_face.png` — tray icon / canonical face

WebP is preferred for runtime character images to keep the public repository compact. PNG and JPG names remain supported as local compatibility fallbacks. Missing assets use a generated placeholder rather than crashing the application.

## Workday mapping

- normal: default/playful
- 17:00 wind-down: worry
- 17:30 leave mode: praise
- 18:00 strong leave: nag
- 18:30 late leave: nag
- 9h active hard stop: nag

After 17:30 no visual/dialogue path may encourage extending work.

## Identity rule

All future poses should preserve the same canonical face, hair, pale-pink top, and ivory-white skirt direction. `master_face.png` is the identity reference for compact UI and future asset work.
