# Character asset contract

The UI is wired to the finalized Kyunghee character set through `asset_manager.py`.

## Runtime file names

The loader accepts PNG first and JPG as a fallback:

- `default_full.png` / `.jpg` — normal main pose
- `playful.png` / `.jpg` — compact playful/default dialogue
- `cheer_full.png` / `.jpg` — stats and stronger encouragement
- `cheer.png` / `.jpg` — compact cheer fallback
- `cute_cheer.png` / `.jpg` — return / light praise
- `nag.png` / `.jpg` — repeated snooze / late-work / hard-stop
- `worry.png` / `.jpg` — first snooze / wind-down / break reminder
- `praise.png` / `.jpg` — leave-mode close-out
- `master_face.png` / `.jpg` — tray icon / canonical face

If an image file is missing, the application falls back to a simple generated placeholder instead of crashing.

## Workday mapping

- normal: default/playful
- 17:00 wind-down: worry
- 17:30 leave mode: praise
- 18:00 strong leave: nag
- 18:30 late leave: nag
- 9h active hard stop: nag

After 17:30 no visual/dialogue path may encourage extending work.

## Repository status

Source code is already wired to these exact names. Binary character files are kept separate from source commits until their final upload path is completed; the application remains runnable without them because the loader has a safe fallback.
