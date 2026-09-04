# Asset Import Workflow

Purpose: repeatable ingestion of user-approved 10-pose character sheets into `assets/` without touching canonical masters or Phase 6 timer behavior.

## Official 10-pose standard

Input is one black/near-black-background image containing exactly 10 poses in a 5x2 layout. Role order is fixed left-to-right, top-to-bottom:

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

Sheet splitting is original-preserving file processing, not image generation. If layout, background, role ownership, or detached props are ambiguous, stop for review rather than guessing.

## Developer importer

Use `tools/import_asset_sheet.py`. Developer-only dependencies remain isolated in `tools/requirements-asset-import.txt`.

```text
python -m pip install -r tools/requirements-asset-import.txt
python tools/import_asset_sheet.py path/to/sheet.png
```

The importer:

- discovers the next set number,
- validates the near-black outer background,
- finds the low-density split between the two logical rows,
- uses distance transform + watershed with one primary marker per role by default,
- associates detached unseeded components by their nominal role cell,
- reports removed/skipped tiny components instead of hiding that loss,
- validates role centroids,
- reports row-overlap tiles that deserve extra human inspection,
- reconstructs soft alpha from the black-matted source edge,
- unpremultiplies edge RGB and bleeds trusted core colour into fully transparent pixels,
- computes SHA-256 plus pose/appearance signatures,
- checks `assets/asset_index.json` for exact and near duplicates,
- writes 10 PNGs, a contact sheet, and a JSON manifest under `.asset_import_preview/set_NN/`.

Manual corrective seeds use **X first, then Y**:

```text
--seed away:985,424
```

### Alpha rule

The source sheet's black background makes edge RGB black-matted. The importer keeps confident interior/core pixels opaque, keeps the outer silhouette out of the core, derives a soft boundary alpha, restores straight RGB by unpremultiplication, then fills fully transparent RGB from the nearest trusted core pixel. This preserves better master PNGs for future translucent rendering and reduces dark matte artefacts in the current resize path.

The runtime still uses binary transparency for the Windows Tk colour-key window. `image_render.py` already resizes in Pillow `RGBa` premultiplied mode and currently uses alpha threshold 112. Do not change that threshold blindly; calibrate it against improved importer outputs first.

### Duplicate rule

The index distinguishes:

- same source SHA-256 — duplicate source; blocked unless explicitly overridden,
- same output SHA-256 — exact duplicate; blocked unless explicitly overridden,
- near duplicate — same role, extremely similar silhouette/luminance **and** close normalized appearance.

A matching pose with different clothing, colour, pattern, or other visible appearance is **not** a duplicate and should not be blocked merely because the silhouette is similar.

Existing sets 01-05 were backfilled into `assets/asset_index.json` as 50 installed outputs. Their original source-sheet hashes are intentionally absent unless known; future imports add source hashes when installed.

Maintenance-only index rebuild:

```text
python tools/backfill_asset_index.py
```

That script does not stage or commit anything. Backfills and bulk regeneration remain manual maintenance operations so the normal importer commit gate stays strict.

## Review and install gate

Human review remains mandatory. Inspect the contact sheet for clipping, neighboring heads/feet, suitcases, charts, gears, wrenches, bells, alert marks, and any row-overlap warning.

After approval:

```text
python tools/import_asset_sheet.py path/to/sheet.png --set NN --install --approved
```

Optional local commit:

```text
python tools/import_asset_sheet.py path/to/sheet.png --set NN --install --approved --commit
```

For a normal import, `--commit` refuses unrelated staged changes and requires **exactly 10 new PNG paths plus `assets/asset_index.json`**. It is intentionally not relaxed for index backfills or bulk replacement jobs.

`IMPORT_ASSET_SHEET.cmd` is the Windows convenience wrapper.

## Preview-directory safety

The importer never recursively deletes an arbitrary existing `--preview-dir`. Existing directories are removed only when they are under the managed `.asset_import_preview/` root or contain the importer sentinel from a previous preview. Repository root, filesystem root, and the user's home directory are always rejected.

`.asset_import_preview/` is already ignored by Git.

## Runtime connection

`asset_manager.py` treats `_01`, `_02`, ... as complete sets rather than independent role variants. A single complete set number is chosen once per process and used across all roles. User-imported image sets still take precedence in the desktop UI; canonical masters remain fallback assets.

A set is runtime-eligible only when all ten role files exist.

## GitHub binary transfer from ChatGPT/connector sessions

When local PNG bytes can be passed directly to GitHub, create binary blobs and build a clean tree from the current target HEAD.

When direct binary transfer is unavailable, use the validated persistent branch `asset-import-transfer-20260904` with the manifest bridge:

1. create a temporary Google Slides file only as a local-file URL bridge,
2. insert the 10 reviewed PNGs and read the signed source URLs,
3. update `.github/asset-import-manifest.tsv` and trigger on the transfer branch,
4. let the transfer workflow download and SHA-256 verify exactly 10 PNGs,
5. read only the verified PNG blob SHAs,
6. build the target tree from the current `ui/dark-kyunghee-redesign` HEAD,
7. include the corresponding `assets/asset_index.json` update in the target commit,
8. never merge the transfer branch itself,
9. compare old and new target HEADs,
10. delete the temporary Slides bridge.

## Completed built-in sets

- Set 01 — `8a520e97322dc827875feacc9c8d5a697b059007`
- Set 02 — `5ef1ac891cacddf3f3d968b84409fe1c09afdb76`
- Set 03 — `cbbff24583f62146533dd4294b447fb4f1c8174e`
- Set 04 — `c8983cca9ed45ec6961d8f2fe029dac911c47810`
- Set 05 — `74c6fa59acb8ec36c4f8c29feb1e1d66b79fa10f`

Current built-in inventory after set 05: 5 complete sets × 10 roles = 50 numbered PNG assets.
