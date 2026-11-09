# Windows smoke test — 승아 타이머 2.1.1

Run this on a real Windows PC before calling the build ready for daily use.

## Setup

1. For a packaged test, extract the Windows ZIP and keep `SeungaTimer.exe` beside `_internal`. Python is not required.
2. For source testing only, install Python 3.12+ and run `python -m pip install -r requirements.txt`.
3. Start the packaged EXE, or use `RUN_DEBUG.cmd` for source debugging.
4. Confirm `%APPDATA%\KyungheeAssistant\kyunghee.log` is being written.

## Must-pass checks

### 0. Review implementation acceptance

- Open a folded long answer by clicking the actual speech bubble. Close it with the button, Esc and titlebar X, then reopen it; also click repeatedly. The timer must stay alive, the whole answer and source links remain readable, and unsent drafts, saved chat and memories remain unchanged. CI now queues native Windows clicks with PostMessageW; synchronous SendMessageW alone did not exercise the fatal boundary in 2.1.0.
- Open chat from the speech bubble; open settings with a short timer/character click; drag without opening settings. Verify tray/keyboard access with the bubble hidden.
- Roll the screen dice, change to away/rest/return, and check situation images return. Explicitly pin and unpin. Restore the latest situation while pinned.
- Open settings/records while away, return to the timer, change scale and save: the timer state and corresponding image must remain consistent.
- Import the user's real complete ZIP, import it again, then try conflicting numbers, incomplete sets and a truncated PNG. Originals and previous selections must survive all failures. Restart and replace the app directory: profile imports should remain.
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
