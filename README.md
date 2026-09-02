# Kyunghee Assistant

Windows productivity timer and virtual secretary.

## Current development target

`0.4.0-alpha`

The 0.4 line is focused on correctness before real-world testing.

## Android UI prototype

`android-prototype/` is a **screen-review-only Android prototype** used to settle the visual language before the same design is carried back to the Windows desktop app.

It intentionally uses fixed sample values and does not implement the Windows timer engine or background activity tracking.

Prototype screens:

- main timer dashboard
- today's stats
- settings
- break reminder preview
- full-body Kyunghee character presentation using `cheer_full.webp` with `ContentScale.Fit` so the legs are not cropped

GitHub Actions workflow: `.github/workflows/android-prototype.yml` builds a debug APK artifact named `kyunghee-ui-prototype-apk`.

### Core timer behavior

- 60 minutes of continuous active use triggers a break reminder.
- Snooze delays the reminder by exactly 5 minutes, repeatedly.
- Manual away starts immediately and ends only on a later keyboard/mouse input.
- The click that starts manual away is explicitly ignored as a resume signal.
- A scheduler/sleep gap over 90 seconds is classified as away, never active.
- If there is no keyboard/mouse input for 5 minutes, the **entire no-input interval** is retroactively reclassified as away.
  - 4m59s idle followed by input remains active use.
  - 5m00s idle becomes 5m00s away.
- App downtime over 60 seconds breaks continuous-session continuity on restart.
- Untracked app downtime is not invented as active or away time.
- Daily statistics roll over at midnight without resetting the global continuous session or break schedule.
- Only the portion of a cross-midnight session that occurred today can become today's longest-continuous statistic.

### Workday-aware behavior

Default pattern:

- usual arrival: around 08:40
- wind-down begins: 17:00
- leaving-work mode: 17:30
- stronger leave-work prompts: 18:00+
- late-work nagging: 18:30+
- hard warning after 9 hours of actual active use

Once leaving-work mode is active, the assistant should stop encouraging additional work and instead encourage wrapping up.

### Reliability

- single-instance protection through a Windows named mutex
- atomic state writes with process-specific temporary files
- corrupt JSON is preserved as a `.corrupt` file before resetting state
- rotating application logs
- Tk UI commands from the tray are marshalled through a queue
- deterministic timer-engine tests use injected clock/wall/idle providers and run on Linux CI

## Privacy

The app does **not** record key contents, window titles, clipboard data, browser data, or typed text.
It only reads last-input timing metadata through Windows `GetLastInputInfo`.

## External review

See [`REVIEW_FOR_CLAUDE.md`](REVIEW_FOR_CLAUDE.md).
The repository is intentionally public so external reviewers can audit the current `main` branch directly.

## Status

Not yet a production release. The next gate is:

1. green deterministic CI
2. external code review of the current `main` branch
3. finalized character/image assets
4. Windows real-world testing
