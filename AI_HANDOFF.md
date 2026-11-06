# Optional AI dialogue, conversation and readability

Status: implemented in an isolated work copy; not deployed or merged.
Date: 2026-11-06 (UTC).
Baseline: `66fb497cf505e0c8209ceb1fc8114e1d9916903e`, PR #3,
`ui/dark-kyunghee-redesign`. The baseline's RUN.cmd and build workflows launch
`desktop_gallery_final.py`; older Notion/PR entrypoint descriptions are stale.

## Behavior and boundaries

The real gallery entrypoint now adds `OptionalAIDesktopMixin`. The original
timer engine, state schema 8, history, break policy, local messages and gallery
selection stay in place. No timer/state/message-engine source was replaced.
AI is OFF by default. A local reply appears immediately; a current AI reply can
replace it. Ordinary ticks do not request AI. Break, return, long-use thresholds,
workday-stage changes, explicit chat and daily-close actions can request it.
Event calls have a 60-second cooldown; chat has a separate 3-second cooldown.
There is one daemon worker and no automatic retry. Socket timeout is 4 seconds;
responses expire after 5 seconds. DNS/OS network operations are not a guaranteed
hard wall-clock deadline, but never run on the Tk/timer thread.

Each reply carries generation and UI-context tokens. New local speech, away,
day, personality, configuration or chat actions invalidate obsolete replies.
The actual app is tested with a blocked mock response while timer accounting
continues, then a state change discards that response. Repeated local/AI lines
are filtered. Significant event codes are kept only for the current day, with
six successful chat turns and a bounded recent-line list in memory. Nothing is
written as long-term AI memory.

The bubble is above the visible head. It has a solid contrasting surface,
padding, wrapping and automatic height. A normal nonmodal window beside the
widget holds user/AI/local labels, input, send, clear and daily-close actions.
It does not change timer state. Pretendard Regular/Medium/SemiBold/Bold are
included unmodified under SIL OFL 1.1, including the full upstream license.
Registration is process-private on Windows, with explicit system-font fallback.
Existing saved font sizes/colors remain valid; only new-install message size is 13.

## Credentials and transmitted information

`UserSettings` adds only `ai_enabled` and `ai_remember_key` booleans. Session-only
is the default. The optional `openai_api_key.dpapi` is current-Windows-user
DPAPI ciphertext written atomically; unsupported systems have no plaintext
fallback. The masked entry is never prefilled. Connection testing is explicit,
asynchronous and may incur API charges. Fixed error codes/messages exclude raw
HTTP bodies and exception strings. Keys are never logged or put in the settings
JSON. Clearing/OFF changes runtime immediately even if saving preferences fails;
this failure path has an actual Tk integration regression test.

Only allowlisted clock/day/enumerated state, rounded usage counters, recent
away/break duration, preset and bounded current-day event codes are included.
Recent AI lines and up to six sanitized chat turns can be sent. Local/custom
lines stay local for repetition filtering, since they may contain private text.
Known key/path/email patterns in chat are redacted; this is not a guarantee that
all sensitive free text can be detected. The user explicitly chooses what to send.
No environment key, organization identifier, credential or private app file is
automatically loaded into prompts.

Official documentation checked on 2026-11-06: Responses API,
`gpt-6-luna`, `reasoning.effort=none`, low verbosity, max 180 output tokens and
`store:false`. Model access and project credits remain account-dependent.
`store:false` disables response storage; it does not exempt requests from
OpenAI's applicable operational/abuse-monitoring data policy.

- https://developers.openai.com/api/docs/models/gpt-6-luna
- https://developers.openai.com/api/docs/guides/text
- https://developers.openai.com/api/docs/guides/your-data
- https://help.openai.com/en/articles/5112595-best-practices-for-api-key-safety
- https://github.com/orioncactus/pretendard/releases/tag/v1.3.9
- https://github.com/orioncactus/pretendard/blob/v1.3.9/LICENSE

## Additional artwork

The original canonical ZIP installer only handles master names and can overwrite
masters. It is retained for compatibility. The new settings action uses
`asset_pack_import.py`: validates all numbered PNGs and all ten roles before
exclusive new-file writes, skips identical files, refuses conflicts/links,
ignores executable/settings/manifest entries, and rolls back newly created
files on failure. Original archives and existing PNGs remain unchanged.
Restarting the app refreshes its complete-set selector/catalog. A restored pack
does not require changing the asset index for runtime discovery.

Drive folder metadata identifies sets01–19 split runtime packages and separate
sets18–22 ZIPs. The standalone `sets01-17_asset_index.json` actually covers only
sets01–05 and12; all 50 common Git hashes match it. Do not infer complete package
contents from that filename. Downloaded archive bytes could not be materialized
because the workspace proxy returns HTTP403; the official file-transfer helper
also failed. Thus packaged executable/source differences and additional pack
completeness were not verified, and no additional Drive images were installed.

Source PNG crop inspection found definite leg/foot cuts in cheer03, warning03,
leave01/05 and stats01/04/05; leave03 is an intentionally cropped seated view,
and leave04 needs original-sheet review. These pixels are already absent in the
PNG. Contain/fit/padding can fix display cropping but cannot restore them.
Preferred recovery is re-extraction from a complete original source sheet.
Without that source, generative extension is newly synthesized content and
needs identity/anatomy/shadow/transparent-edge review. No artwork was regenerated,
cropped, overwritten, or claimed repaired in this task. Two legacy baseline
fallback files fail decoding (`cheer_full.webp`, `master_face.png`); all 50
numbered PNGs decode. These pre-existing files were preserved.

## Validation and remaining checks

- Baseline: 109 existing tests passed before implementation.
- Final full suite with real Tk8.6/Xvfb: 175 tests, all passing, one Windows-only
  DPAPI test skipped. Tests include mocked API auth/network/timeout/bad-body/
  repeat/cooldown/stale/privacy, credential persistence failures, old settings,
  actual gallery chat/timer integration, additive packs and font selection.
- Real Tk geometry: 80/110/200% scale × 9/13/16 message size, very long speech,
  show flags, click/drag bindings, chat input/footer and AI settings inspected.
- Python compilation and `git diff --check` passed.
- Linux PyInstaller dependency collection completed; it is not a Windows build
  and reported unresolved custom-runtime Tcl9 libraries. It is not a runnable
  release or a substitute for Windows smoke testing.
- No user API key was available: no live API, actual MIN credits/model access or
  naturalness of live model output was tested.
- Real Windows DPAPI, font registration, color-key transparency/click-through,
  hotkeys, tray, DPI/multimonitor and EXE build/smoke still need Windows validation.
  The existing Windows workflows include the new source modules and assets.
- Local `gh` authentication is invalid. No remote branch/PR or Windows workflow
  was created through that credential, and no existing branch/build was changed.

Local evidence directory: `/workspace/kyunghee-evidence` (screenshots, geometry,
asset hash/crop audit and Linux packaging analysis). User-facing API key fields
in captured UI are blank; no real key or user chat is included.

## Windows review sequence

1. Use a separate folder and `RUN_AI_REVIEW.cmd`. It redirects this process's
   APPDATA to `%LOCALAPPDATA%/KyungheeTimer_AI_Review`, preserving the normal
   installation's data. Exit the normal tray app first because the existing
   single-instance mutex is retained. The original RUN.cmd/direct entrypoint
   still uses normal app data. For compatibility checks, use copies of backed-up
   state/settings in the isolated review directory, never the only originals.
2. Compile, run the full unit suite, build with the existing Windows workflow and
   confirm the packaged entrypoint stays alive and starts without logged errors.
3. Confirm old preferences/history, timer, idle/manual away/return, break snooze,
   daily suppression, workday stages, gallery/custom assets, click/drag, hiding,
   hotkeys and multi-monitor behavior.
4. Check default OFF/no-key behavior. Enter the user's key only in the masked app
   field, test a session key and explicit connection test, then separately test
   DPAPI remember/relaunch/clear and deliberate storage failure.
5. Simulate network/auth/quota/late replies; confirm immediate local fallbacks,
   responsive ticking and stale-response rejection. Inspect natural short Korean
   responses across presets, return/break/long use/workday/chat/day close.
6. Review bubble/chat at Windows DPI and 80–200% scales. Import a copied complete
   extra pack, verify original hashes and confirm conflict refusal. Repair cropped
   source assets only in new copies after source or generative quality review.
