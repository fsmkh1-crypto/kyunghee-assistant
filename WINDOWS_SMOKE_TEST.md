# Windows smoke test — 승아 타이머 2.1.5

Run this on a real Windows PC before calling the build ready for daily use.

## Setup

1. Exit the previously running timer. Extract the new ZIP into a separate folder and keep `SeungaTimer.exe` beside `_internal`. Python is not required. Check the chat title says **2.1.5** and `BUILD_INFO.txt` names the intended commit; the single-instance guard can otherwise leave the old app running.
2. For source testing only, install Python 3.12+ and run `python -m pip install -r requirements.txt`.
3. Start the packaged EXE, or use `RUN_DEBUG.cmd` for source debugging.
4. Confirm `%APPDATA%\KyungheeAssistant\kyunghee.log` is being written.
5. For a local offline IME check, run `IME_INPUT_TEST.cmd` beside the packaged EXE. Set Korean Hangul mode during the preparation countdown, then leave input alone. The separate temporary chat uses a fixed `ㅋ`, a fake service and blocked networking; it never loads personal keys/history. The console prints a unique temporary JSON path. Exit 3 means unavailable, not passed. Actual IME automation is still distinct from physical typing of the full reported phrase.

## Must-pass checks

### 0. Review implementation acceptance

- **2.1.5 IME follow-up:** Record the visible running version and whether the user sends with the button or Ctrl+Enter. With Microsoft Korean IME, physically type `근데 느림...ㅋ`; do not paste it. Send with the final jamo still composing, with Ctrl held/released, and after Tab to the send button. Repeat at the middle of a line, replacing selected text, and with mixed Korean/jamo/Latin/emoji. Normal Ctrl+A/C/V/Z and plain Enter must remain normal editing/newline operations. Compare the sent bubble and saved/reopened history. Use only a local fake API for request inspection; do not collect real conversation contents or keys.
- **2.1.5 cancellation:** Escape/close or switch away during composition completion, reopen, and check the draft remains and no message was sent. Repeat rapid send activation and API failure; there must be at most one submission, and failed text must remain available. Do not interpret waiting for composition as a failed network request.
- **2.1.5 test evidence:** `windows-ime-report.json` distinguishes real Microsoft Korean IME composition produced by keyboard input from committed-text insertion and synthesized Windows-message tests. `unavailable` means this runner could not prove active IME composition; report the reason and perform the physical input checks. Neither mocked IME state nor a directly inserted string proves the original user scenario.

- **2.1.4 IME:** With Microsoft Korean IME, type (do not paste) `근데 느림...ㅋ` and send while the final `ㅋ` is still composing. Repeat via Send, Ctrl+Enter (including holding then releasing Ctrl), rapid repeated sends, Escape/close during commit, and mixed Korean/emoji. Sent bubble, saved history after restart, and the captured request text in an isolated fake-transport test must match; never log real API keys. Plain Enter remains newline. Automated delayed-commit tests are not proof of this physical IME scenario.
- **2.1.4 reading:** Load more than 40 turns, scroll to an older paragraph, receive a break/return message, load older history, resize and hide/reopen. Preserve the paragraph being read; at the bottom, follow new messages. At narrow/high-DPI sizes, history and Send/Cancel remain accessible.
- **2.1.4 unified history:** Start a break, return manually/automatically and snooze. Confirm each actual notification appears once with its timer source; routine worry/nag lines must not flood history. Successful displayed AI messages use their own source. Cancelled, stale or discarded AI results must not be recorded as displayed. Check history OFF/ON, restart, deletion, export and backup/restore with a test profile.
- **2.1.4 cadence:** In normal mode with proactive ON, chatter OFF and a one-minute interval, snooze and wait beyond real conversation protection. Routine worry/nag must not repeatedly reset the important-alert clock. Separately cancel a delayed chat and wait for its old transport to finish: this must not restart the five-minute clock. Existing actual reading/typing, important alerts, away and API limits still apply.


- In image settings, follow imported set 26 and select the normal role. Previous/next must browse different situation images with an accurate caption; browsing must not change the selected set or saved preferences. Repeat with a built-in set, a single custom image and a multi-image custom group.
- For every image role, physically click the visible single/multiple/folder/follow/gallery/random controls. Browse to `settings_04.png` while targeting normal, then press Apply: the normal role must use that exact image. Verify the applied filename, Undo and restart. While away, changing the normal image must preserve away state and apply when normal returns. Repeat with imported set 26 at 100/125/150/200% scaling.
- Ask for a break or away transition. At 100/125/150/200% Windows scaling, shrink the approval window and scroll its long description: Apply and Cancel must remain reachable. Repeat with an image proposal and its preview. Cancel must leave the timer/image unchanged; Apply must perform it once.
- Start manual away and watch the main clock for at least 20 seconds without input. Check the away clock advances while active time stays unchanged. Return and compare today's away record; repeat with automatic idle and crossing midnight.
- Close and reopen a chat containing a long AI answer and an unsent draft. The latest answer, conversation and draft must remain available. Explicit dismissal/new conversation and important break/leave alerts must still work.
- Let normal local messages change several times and check that recent lines do not repeat immediately. With both proactive AI and AI chatter disabled, or Today Quiet enabled, there must be no proactive API request. With a mode enabled, check event/periodic controls, spacing and contextual messages; an active conversation or draft must not be interrupted. Real API requests use the user's configured account and limits.
- Scroll a long Korean/emoji/URL reply inside the actual speech bubble using the wheel, scrollbar and keyboard. At most three lines may be visible; reach the final sentence without a separate popup. Click the border repeatedly, scroll, resize/change scale, hide/reopen chat and dismiss the reply. The timer must stay alive and drafts/history/memories unchanged. CI exercises asynchronous native Windows input with PostMessageW; synchronous SendMessageW alone missed the fatal boundary in 2.1.0.
- Open chat with the bubble's explicit chat button; open settings with a short timer/character click; drag without opening settings. Verify tray/keyboard access with the bubble hidden.
- In AI settings, set the interval to one minute and save. Existing saved intervals must not silently change. With proactive AI ON, normal work mode, no draft/request and no recent conversation, leave an empty chat open: it must no longer block indefinitely. Inspect the current waiting reason and last result for disabled events, quiet day, draft, recent activity, no key, exhausted budget, SILENT and network errors. Use fake clients first; live API checks incur the user's usage.
- Toggle chatter separately: it requires AI and a key and displays only AI-generated lines at the configured interval, default one minute for new settings. It also works with proactive AI OFF; enabling both must share one schedule and budget. Test typing, scrolling/reading, away, urgent timer alerts, immediate OFF and late responses. Chatter must not create a second API stream or modify timer/image state. Turning chatter OFF leaves separately enabled proactive AI enabled; turn both OFF or use Today Quiet to stop automatic AI requests.
- Roll the screen dice, change to away/rest/return, and check situation images return. Explicitly pin and unpin. Restore the latest situation while pinned.
- Open settings/records while away, return to the timer, change scale and save: the timer state and corresponding image must remain consistent.
- Import the user's real complete ZIP, then import it again: byte-identical complete sets should be reused. Try a different set whose number collides with built-in or imported art: the preview and completion must show one next-free higher number shared by all ten roles. Check consecutive collisions, multiple incoming numbers and exhausted 01..99 space. Cancel the preview, then try differing duplicate role/number entries, incomplete sets and a truncated PNG: original files, manifests and previous selections must remain. Restart and replace the app directory: profile imports should remain.
- Change a whole set and one role, select a custom image, follow the set, and undo. Check displayed origin, saved state and restart. In chat, verify no change before Apply, ambiguous scope, Cancel, Undo, stale proposals and repeated Apply.
- Edit unrelated settings while applying an image in chat; neither edit may overwrite the other. Close/reopen AI settings: drafts remain, key input follows its displayed handling rule.
- At 1366×768 and 100/125/150/200% Windows scaling, inspect all tabs, gallery, chat, API settings, memories, weather and backup. Save/action controls must be reachable. Test left-side negative-coordinate monitors and unplug/reconnect a monitor.
- Test Korean IME composition and Ctrl+Enter, Tab/Shift+Tab, Enter on a source, text enlargement, Narrator/NVDA, and always-on-top interactions.
- With synthetic delayed API responses, cancel and send again immediately; late results must not replace the current response. Retry an error after an approved timer action: the completed action must not repeat.
- Test invalid keys, offline mode, timeouts and exhausted limits. Timer/alerts and offline status/image controls must keep working. Event fallback must appear immediately, with stale/repeated AI lines suppressed.
- Check session-only keys disappear after restart and saved keys decrypt only in the intended Windows account. Run the explicit live connection test only with the user's own key and consent to its API usage.
- Toggle history saving OFF→ON→OFF and memory usage independently. Current chat must remain readable; earlier temporary chat must not be silently persisted. Check memory edit/pin/duplicate/length and scoped deletion counts.
- Back up selected temporary test data, inspect it, restore, restart and compare. Inject a failure and confirm rollback. Keys must be absent and diagnostics must omit personal content. Do not test destructive restoration against the only copy of real data.

The CI job runs the packaged `--self-test <report.json>` route using a temporary profile, blocked network transport and Tk scales 96/120/144/192. Its JSON report is included in the package. This does not replace physical-monitor, IME, screen-reader, sleep or live API tests.

### 1. Single instance

- Launch the app.
- Launch it again.
- Expected: a second tracker process must not start.

### 2. Manual away click grace

- Click `자리비움`.
- Move the mouse during the first 10 seconds.
- Expected: the break must remain active.
- After 15+ seconds, provide a new keyboard/mouse input.
- Expected: return is detected and the away duration is shown.

### 3. Five-minute idle policy

- Stop all keyboard/mouse input for at least 5 minutes.
- Expected: the entire no-input interval is reclassified as away, not just the portion after minute five.
- Provide a new input.
- Expected: the return tick is still away; active tracking resumes on the following tick.

### 4. Sleep / lid-close test (V-1)

- Accumulate at least 2 minutes of active use.
- Note current `continuous_seconds`.
- Put the machine to sleep (or close the laptop lid) for 5+ minutes.
- Wake it with keyboard/mouse input.
- Expected:
  - sleep interval is away, never active;
  - continuous session resets to zero;
  - return notification appears;
  - log contains a long-gap transition.

This is the one test that cannot be fully proven by CI because Windows sleep-clock behavior is hardware/power-mode dependent.

### 5. Break + snooze

- For practical testing, temporarily reduce the break interval locally or use the automated tests.
- Verify first break reminder appears once due.
- Press `5분 더`.
- Expected: next reminder is exactly five minutes later.
- Repeat snooze and confirm another exact five-minute interval.

### 6. Workday transitions

Verify the UI policy around these local times:

- 17:00 — wind-down
- 17:30 — leave-work mode
- 18:00 — strong leave prompt
- 18:30 — late-work nag
- 9 hours actual active use — hard-stop warning regardless of wall-clock time

After leave-work mode begins, the app must not encourage starting more work.

### 7. Stats page

- Open `오늘 기록`.
- Expected: numbers update, but the praise/stats sentence does not change every second.

### 8. Persistence / restart

- Accumulate some daily stats and exit normally.
- Restart within 60 seconds: short session continuity may be preserved.
- Restart after more than 60 seconds: continuous session must reset while daily totals remain.

## Pass criteria

Daily-use candidate requires:

- GitHub Actions green on Ubuntu + Windows runners;
- all must-pass checks above successful;
- especially sleep/lid-close test successful on the target Windows PC.
