# Windows smoke test — 0.4.0 alpha

Run this on a real Windows PC before calling the build ready for daily use.

## Setup

1. Install Python 3.12+.
2. Run `python -m pip install -r requirements.txt`.
3. Start with `RUN_DEBUG.cmd` for the first test session.
4. Confirm `%APPDATA%\KyungheeAssistant\kyunghee.log` is being written.

## Must-pass checks

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
