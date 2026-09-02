# Finalized character assets

The app uses one consistent character identity and ivory-white outfit direction.

## Asset roles

- `master_face.png` — canonical face / tray icon / compact neutral toast (**committed**)
- `default_full.png` — page 1 main/default playful pose
- `cheer_full.png` — page 2 stats / fighting pose
- `cute_cheer.png` — short praise / return / light encouragement
- `nag.png` — repeated snooze / 18:30+ late-work nagging
- `worry.png` — first snooze / long-session concern / 17:00 wind-down
- `praise.png` — good break / daily praise / 17:30 leave-mode transition
- `playful.png` — compact normal toast

The remaining PNGs are being committed in batches because binary assets are larger than normal source files.

## Workday mapping

- normal: default/playful
- 17:00 wind-down: worry
- 17:30 leave mode: praise / close-out tone
- 18:00 strong leave prompt: nag / firm close-out
- 18:30 late leave: nag
- 9h active hard stop: nag / firm stop

No post-17:30 mode should actively encourage starting more work.
