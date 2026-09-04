# Asset Import Workflow

Purpose: repeatable ingestion of user-approved character image sheets into `assets/` without touching existing canonical masters or Phase 6 logic.

## Official 10-pose sheet standard
The standard input is one black/near-black-background image containing exactly 10 poses in a 5x2 layout. Role order is fixed left-to-right, top-to-bottom:

1. `default`
2. `cheer`
3. `rest`
4. `away`
5. `warning`
6. `leave`
7. `stats`
8. `settings`
9. `alert`
10. `profile`

Do not route a sheet-splitting task through image generation. It is an original-preserving file-processing task. If the sheet does not follow the expected 5x2 order/background or the automatic split is ambiguous, stop for review instead of guessing.

### Developer importer
Use `tools/import_asset_sheet.py`. Its extra dependencies are isolated in `tools/requirements-asset-import.txt` and are not added to the runtime app requirements.

First install the developer dependencies:

```text
python -m pip install -r tools/requirements-asset-import.txt
```

Preview only:

```text
python tools/import_asset_sheet.py path/to/sheet.png
```

The tool automatically finds the next variant number, uses multi-seed distance-transform/watershed segmentation, associates detached foreground pieces by their nominal 5x2 role cell, removes tiny fragments, writes 10 transparent PNGs, computes SHA-256 values, and creates a contact sheet plus JSON manifest under `.asset_import_preview/set_NN/`.

**Human review is a hard gate.** Inspect the contact sheet for body-part clipping, neighboring-pose contamination, and detached props such as suitcases, charts, gears, wrenches, bells, or alert marks. If a prop needs correction, add one or more `--seed ROLE:X,Y` overrides and regenerate the preview.

After visual approval:

```text
python tools/import_asset_sheet.py path/to/sheet.png --set NN --install --approved
```

Optional local commit:

```text
python tools/import_asset_sheet.py path/to/sheet.png --set NN --install --approved --commit
```

`--commit` refuses to run if unrelated staged changes already exist and requires the staged set to be exactly the 10 expected PNG paths. `IMPORT_ASSET_SHEET.cmd` is the Windows convenience wrapper for the same tool.

## Standard repository flow
1. Receive the source sheet.
2. Run the developer importer in preview mode; split by subject/object boundaries rather than fixed rectangular crops.
3. Preserve transparent PNG output; keep dark hair/interior detail and remove the near-black sheet background.
4. Visually inspect all 10 outputs in the generated contact sheet before any repository write.
5. Keep the fixed role-to-folder mapping: `default`, `cheer`, `rest`, `away`, `warning`, `leave`, `stats`, `settings`, `alert`, `profile`.
6. Use additive variant names: `<role>_01.png`, then `_02`, `_03`, etc. Never overwrite canonical masters unless explicitly approved.
7. Install or transfer only the 10 reviewed PNGs.
8. Build one clean target commit from the current `ui/dark-kyunghee-redesign` HEAD and fast-forward it.
9. Compare old HEAD vs new HEAD. Expected result for one set: exactly 10 added PNG files and zero code/canonical changes.
10. Keep Phase 6 behavior untouched during asset-only imports.

## GitHub binary transfer paths
### Preferred direct path
When local PNG bytes can be passed directly to GitHub:
- Generate and visually verify the 10 final PNGs locally.
- Compute SHA-256 for each final file.
- Create GitHub binary blobs from the final bytes.
- Create a tree containing only the new asset paths, using the current target branch tree as `base_tree_sha`.
- Create one asset commit and fast-forward the target branch.
- Run `compare_commits` as the final gate.

### Validated manifest bridge fallback
When the connector cannot accept the local PNG bytes directly, use the tested bridge instead of manual base64/chunk transfer:
1. Reuse the persistent transfer branch `asset-import-transfer-20260904` rather than creating a new branch for every set.
2. Create a temporary Google Slides presentation only as a local-file URL bridge.
3. Insert all 10 reviewed local PNGs in one batch and read back each exact signed image source URL.
4. Update only `.github/asset-import-manifest.tsv` on the transfer branch. Each row contains target path, local SHA-256, and signed source URL.
5. Change `.github/asset-import-trigger` to start the stable transfer workflow.
6. The workflow accepts only the 10 known role paths, requires exactly 10 assets, downloads each file, verifies SHA-256, and requires exactly 10 staged files before committing to the transfer branch.
7. Read only the verified PNG blob SHAs from the staged transfer commit.
8. Build a clean tree from the current `ui/dark-kyunghee-redesign` HEAD using only those 10 blob SHAs. Never merge the transfer branch itself.
9. Create one clean asset commit, fast-forward the target branch, and require `compare_commits` to show exactly the intended PNG additions.
10. Delete the temporary Google Slides presentation after staging succeeds.

The original bridge was validated with set 02. The **generic manifest-driven workflow was validated with set 03**, so future sets should update the small manifest and trigger instead of rewriting the workflow YAML.

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

### Set 03
Imported on 2026-09-05 KST as commit `cbbff24583f62146533dd4294b447fb4f1c8174e`:
- `assets/default/default_03.png`
- `assets/cheer/cheer_03.png`
- `assets/rest/rest_03.png`
- `assets/away/away_03.png`
- `assets/warning/warning_03.png`
- `assets/leave/leave_03.png`
- `assets/stats/stats_03.png`
- `assets/settings/settings_03.png`
- `assets/alert/alert_03.png`
- `assets/profile/profile_03.png`

Verification: parent `dd54854ad4b0bb6f9f1c551b18c942bf3e19ba8c`; one commit ahead; exactly 10 PNG files added; no code or canonical master files changed. The manifest-driven transfer workflow required exactly 10 files and verified every transferred PNG against the locally computed SHA-256 before the clean target commit was built.
