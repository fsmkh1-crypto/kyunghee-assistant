# Kyunghee Assistant

Windows productivity timer and virtual secretary.

## Current development target

`0.4.0-alpha`

The 0.4 line is focused on correctness before real-world testing:

- 60-minute active-use break reminders
- exact 5-minute snooze behavior
- manual away that does not immediately cancel itself
- long scheduler/sleep gaps classified as away
- session reset after untracked app downtime
- single-instance protection
- safe state persistence
- deterministic timer-engine tests with injected clock/idle providers
- workday-aware behavior
  - usual arrival: around 08:40
  - wind-down begins: 17:00
  - leaving-work mode: 17:30
  - stronger leave-work prompts: 18:00+
  - hard safety prompt after 9 hours of actual use

## Privacy

The app does **not** record key contents, window titles, clipboard data, or typed text.
It only reads last-input timing metadata through Windows `GetLastInputInfo`.

## Review

See [`REVIEW_FOR_CLAUDE.md`](REVIEW_FOR_CLAUDE.md) for the current audit checklist.

## Status

This repository is public for external code review. It is not yet a production release.
