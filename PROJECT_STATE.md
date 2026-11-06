# Current timer work — 2026-11-06

Status: optional AI/chat/readability implemented locally; no deployment or merge.

- Repository baseline: PR #3, `ui/dark-kyunghee-redesign`, commit
  `66fb497cf505e0c8209ceb1fc8114e1d9916903e`; main is the older UI.
- Work copy: `/workspace/kyunghee-ai-work`, branch `feature/optional-ai-dialogue`.
- Actual launch/build entrypoint: `desktop_gallery_final.py`.
- Added opt-in Responses API dialogue, safe key UI/DPAPI, short conversation,
  head-level bubble, licensed Pretendard and additive numbered pack import.
- `RUN_AI_REVIEW.cmd` launches source with separate review data; original RUN.cmd
  remains unchanged for the normal installation.
- Timer engine, state/history schema, messages, canonical artwork and original
  deployment remain preserved. No real user key was requested or used.
- Validation: 175 tests pass with one Windows-only skip, including real Tk
  integration under Xvfb; details and source references are in `AI_HANDOFF.md`.
- Drive metadata and partial manifests read; archive transfer blocked HTTP403.
  Additional ZIP contents/installed identity remain unverified. Several existing
  PNGs contain source-level limb cuts; none were regenerated or claimed repaired.
- Remaining: Windows EXE build/smoke, DPAPI and native UI checks, live API with
  the user's own project key, transfer/review of extra asset packs, source-sheet
  recovery or separately reviewed generative extension for clipped artwork.
- Prohibited: merge/deploy the canonical release, replace existing user data or
  originals, treat padding/cropping as recovery of missing anatomy, or claim the
  current installed build matches this baseline without verification.
