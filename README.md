# 승아 타이머

Windows productivity timer and virtual secretary.

## Current development target

`2.1.3` — makes situation-image selection and application accessible, displays long speech in a three-line scrollable bubble, and adds configurable one-minute proactive conversation and a separate chatter toggle. Preserves the native speech-click crash fix, away-clock and conversation fixes, and complete review implementation based on Seunga Timer 2.0.3 (`15accd3`).

The implementation and verification ledger is [docs/IMPLEMENTATION_CHECKLIST_2_1.md](docs/IMPLEMENTATION_CHECKLIST_2_1.md). Windows acceptance steps and remaining physical-device checks are documented separately; automated checks do not imply a live API quality test.

## Desktop app

Development is focused on the Windows desktop app. `RUN.cmd` and Windows source autostart launch `desktop_gallery_final.py`. The Windows job in the **tests** workflow publishes `seunga-timer-2.1.3-windows-x64` for branch pushes. Sign in to GitHub, open the successful workflow run, then select the package under **Artifacts**. Keep `SeungaTimer.exe` beside its `_internal` folder. The package includes Python.

- Read long speech by scrolling inside the bubble (at most three visible lines). Use its explicit chat button, tray or keyboard shortcut to open chat. Click the timer/character for settings; drag them to move the widget.
- Screen dice changes the current image until the next situation. Explicit pinning and restoration are available.
- Import complete image ZIP sets from the image settings tab. Imports live in the user profile and do not overwrite built-in artwork.
- Image changes from chat use a validated proposal, explicit Apply/Cancel, and Undo. Local image controls do not require an API key.
- Settings have tabs, a fixed save area, draft indicators and discard. Gallery selections are previews until Apply is pressed; that action saves separately from general settings and has its own Undo.
- Optional AI supports cancellation, retry/edit, local timer status, separate history/memory preferences, searchable/editable pinned memories, event controls and web search preferences.
- Proactive conversation has a visible on/off control, 1–120 minute interval and current waiting/result status. New settings default to one minute; existing saved choices are preserved. Chatter is a separate optional AI-only mode using the same interval and bounded scheduler; enabling both modes does not duplicate requests.
- Choose a session-only API key or Windows DPAPI storage. Connection testing is an explicit API request and may incur usage.
- Selective user-data backup, validated restore with a recovery snapshot, and privacy-preserving diagnostics are available in the data panel. Keys are excluded.

For the Seunga Timer Windows package, see the [Korean installation and usage guide](docs/AI_ASSISTANT_2_GUIDE.md).

The earlier `android-prototype/` is retained only as inactive design history and is not a current development target.

The settings page now persists and applies:

- Windows sign-in startup
- always-on-top mode
- break reminder on/off
- workday reminder on/off
- wind-down, leave, strong-leave, and late-leave times

User preferences are stored in `%APPDATA%\KyungheeAssistant\settings.json`.

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

Timer activity tracking reads last-input timing metadata through Windows `GetLastInputInfo`.
When you enable the optional AI assistant, messages you send and relevant context are sent to OpenAI for a response. You can opt in to saving conversation history and memory locally with a separate setting.

## External review

See [`REVIEW_FOR_CLAUDE.md`](REVIEW_FOR_CLAUDE.md).
Review the implementation branch and its exact commit, rather than assuming `main` contains the current desktop product.

## Status

No automatic merge is part of this work. See the implementation ledger for verified checks, Windows package results, and the manual acceptance items that remain.
