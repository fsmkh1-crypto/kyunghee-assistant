# Asset Import Workflow

Purpose: repeatable ingestion of user-approved character image sheets into `assets/` without touching existing canonical masters or Phase 6 logic.

## Standard flow
1. Receive the source sheet in chat.
2. Split by actual subject/object boundaries rather than fixed grid crops.
3. Preserve transparent PNG output; keep dark hair/interior pixels intact and only remove true connected background.
4. Visually inspect all outputs in a contact sheet before repository writes.
5. Map roles to folders: `default`, `cheer`, `rest`, `away`, `warning`, `leave`, `stats`, `settings`, `alert`, `profile`.
6. Use additive variant names: `<role>_01.png`, then `_02`, `_03`, etc. Never overwrite canonical masters unless explicitly approved.
7. Transfer PNG bytes as GitHub binary blobs, assemble one clean tree from the current target branch HEAD, create one commit, and fast-forward `ui/dark-kyunghee-redesign`.
8. Compare old HEAD vs new HEAD. Expected result for one 10-image set: exactly 10 added PNG files and zero code/canonical changes.
9. Keep Phase 6 behavior untouched during asset-only imports.

## Optimized path
Preferred when local PNG bytes are available in the session:
- Generate/verify the 10 final PNGs locally.
- Create GitHub blobs with base64 encoding directly from the final PNG bytes.
- Create a tree with only the new asset paths, using the current branch tree as `base_tree_sha`.
- Create one commit and fast-forward the target branch.
- Run `compare_commits` as the final gate.

If direct binary transfer is unavailable in a future session, use a temporary transfer branch/workflow only as a fallback, verify SHA-256 before staging, then build a clean final tree from the target branch HEAD. Temporary transfer artifacts must not be merged into the target branch.

## Current completed set
Imported on 2026-09-05 KST as commit `8a520e97322dc827875feacc9c8d5a697b059007`:
- `assets/default/default_01.png`
- `assets/cheer/cheer_01.png`
- `assets/rest/rest_01.png`
- `assets/away/away_01.png`
- `assets/warning/warning_01.png`
- `assets/leave/leave_01.png`
- `assets/stats/stats_01.png`
- `assets/settings/settings_01.png`
- `assets/alert/alert_01.png`
- `assets/profile/profile_01.png`

Verification: parent `886e62ee7a765cad1e78f4f5adf8f9df7dc07503`; one commit ahead; exactly 10 files added; no code files changed.
