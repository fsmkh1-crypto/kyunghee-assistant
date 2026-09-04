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
### Preferred direct path
When local PNG bytes can be passed directly to GitHub:
- Generate and visually verify the 10 final PNGs locally.
- Compute SHA-256 for each final file.
- Create GitHub binary blobs from the final bytes.
- Create a tree containing only the new asset paths, using the current target branch tree as `base_tree_sha`.
- Create one asset commit and fast-forward the target branch.
- Run `compare_commits` as the final gate.

### Validated bridge fallback
When the connector cannot accept the local PNG bytes directly, use this tested bridge instead of manual base64/chunk transfer:
1. Reuse the persistent transfer branch `asset-import-transfer-20260904` rather than creating a new branch for every set.
2. Create a temporary Google Slides presentation only as a local-file URL bridge.
3. Insert all final local PNGs in one `batch_update_presentation` call with local `image_uris`.
4. Read the presentation back and collect each image `sourceUrl` signed URL. The URL points to the exact local image bytes used for insertion.
5. On the transfer branch, have GitHub Actions download those URLs and verify every file against the locally computed SHA-256 before committing anything.
6. After successful verification/staging, read only the staged PNG blob SHAs from the transfer branch.
7. Build a clean tree from the current `ui/dark-kyunghee-redesign` HEAD using only those PNG blob SHAs. Never merge the transfer branch itself.
8. Create one clean asset commit, fast-forward the target branch, and require `compare_commits` to show exactly the intended PNG additions.
9. Delete the temporary Google Slides presentation after staging succeeds.

This fallback was validated with asset set 02. It avoids large base64 payloads in chat/tool calls and keeps temporary workflow/trigger changes completely out of the target branch.

### Next optimization for repeated imports
Keep the transfer workflow generic and stable, and update only a small manifest containing `role/path`, signed source URL, and SHA-256 plus one trigger value. This removes the need to rewrite the workflow YAML for each future set and should make `_03` and later imports faster and less error-prone.

## Completed sets
### Set 01
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

### Set 02
Imported on 2026-09-05 KST as commit `5ef1ac891cacddf3f3d968b84409fe1c09afdb76`:
- `assets/default/default_02.png`
- `assets/cheer/cheer_02.png`
- `assets/rest/rest_02.png`
- `assets/away/away_02.png`
- `assets/warning/warning_02.png`
- `assets/leave/leave_02.png`
- `assets/stats/stats_02.png`
- `assets/settings/settings_02.png`
- `assets/alert/alert_02.png`
- `assets/profile/profile_02.png`

Verification: parent `a09b736b9da1e80e9e47c4ec818fa51f5dbd37d6`; one commit ahead; exactly 10 PNG files added; no code or canonical master files changed. GitHub Actions staging also verified every transferred PNG against its local SHA-256 before the target tree was created.
