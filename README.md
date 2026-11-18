# 승아 타이머

Windows productivity timer and virtual secretary.

## Current development target

`2.1.8` fits complete images to the timer viewport without cutting heads or feet, including legacy crop settings, and aligns previews with runtime rendering. See [image window fit](docs/IMAGE_WINDOW_FIT_218.md).

`2.1.7` keeps only GPT-6.2 Sol and GPT-6.2 Astra in AI settings. Existing model selections migrate to Sol, with other settings and user data preserved. See [GPT-6.2 update](docs/GPT62_UPDATE.md).

`2.1.6-hotfix.1` is a repair candidate based on the 2.1.6 release. It corrects per-date time accounting at midnight, interrupted backup restores, invalid numeric state fields on startup, and disabled break reminder labels. Windows packaging and physical-device verification are separate from the source tests. See [핫픽스 검증 및 사용 안내](docs/HOTFIX_216_1.md).

`2.1.6` — adds named whole image sets assembled from multiple loose files. Assign all ten situations, review the final name and images, save without changing the current selection, then explicitly apply or reselect the set later. Existing image overrides, numbered ZIP sets and backups remain supported. Preserves 2.1.5's Korean input handling and unified timer notices, as well as the earlier timer, chat, inline scrolling and configurable AI features.

The implementation and verification ledger is [docs/IMPLEMENTATION_CHECKLIST_2_1.md](docs/IMPLEMENTATION_CHECKLIST_2_1.md). Windows acceptance steps and remaining physical-device checks are documented separately; automated checks do not imply a live API quality test.

See [named whole image sets assembled from loose files](docs/NAMED_IMAGE_SETS.md). This feature is not included in the previously delivered 2.1.5 ZIP. Source tests, Wine checks and actual Windows package tests are separate verification levels; use the report accompanying a particular build.

## Desktop app

Development is focused on the Windows desktop app. `RUN.cmd` and Windows source autostart launch `desktop_gallery_final.py`. A successful Windows job in the **tests** workflow produces a versioned Windows artifact. When using an authorized GitHub build, sign in and select the package under **Artifacts**. Exit the old running app, extract the new ZIP into its own folder, and keep `SeungaTimer.exe` beside its `_internal` folder. For this hotfix, check the chat title for `2.1.6-hotfix.1`; `BUILD_INFO.txt` identifies the package source. The executable package includes Python. For a local Windows source build with Python installed, use `BUILD_WINDOWS.cmd`; its output is separate from older packages.

- Read long speech by scrolling inside the bubble (at most three visible lines). Use its explicit chat button, tray or keyboard shortcut to open chat. Click the timer/character for settings; drag them to move the widget.
- Screen dice changes the current image until the next situation. Explicit pinning and restoration are available.
- Import complete image ZIP sets from the image settings tab. Conflicting numbered sets receive the next available higher number, consistently across all ten roles; the preview shows the mapping. Imports live in the user profile and preserve existing artwork. Byte-identical complete sets are reused.
- Timer notices continue in the main speech bubble and conversation history without a second automatic notification window. Break, snooze and quiet-today actions remain available from the tray menu.
- Image changes from chat use a validated proposal, explicit Apply/Cancel, and Undo. Local image controls do not require an API key.
- Settings have tabs, a fixed save area, draft indicators and discard. Gallery selections are previews until Apply is pressed; that action saves separately from general settings and has its own Undo.
- Optional AI supports cancellation, retry/edit, local timer status, separate history/memory preferences, searchable/editable pinned memories, event controls and web search preferences.
- Proactive conversation has a visible on/off control, 1–120 minute interval and current waiting/result status. New settings default to one minute; existing saved choices are preserved. Chatter is a separate optional AI-only mode using the same interval and bounded scheduler; enabling both modes does not duplicate requests.
- Choose a session-only API key or Windows DPAPI storage. Connection testing is an explicit API request and may incur usage.
- Selective user-data backup, validated restore with a recovery snapshot, and privacy-preserving diagnostics are available in the data panel. Keys are excluded.

For the Seunga Timer Windows package, see the [Korean installation and usage guide](docs/AI_ASSISTANT_2_GUIDE.md).

The package's `IME_INPUT_TEST.cmd` runs an isolated offline IME check through `SeungaTimer.exe --ime-self-test <report.json>`. It uses fixed input and a fake service, blocks networking, and leaves personal profiles untouched. User mode does not install/load an input locale or toggle the IME automatically. It reports unavailable separately from passed. This is actual IME automation where available, not proof of physical keyboard behavior on every PC.

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
