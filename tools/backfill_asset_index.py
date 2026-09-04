#!/usr/bin/env python3
"""Rebuild assets/asset_index.json from installed numbered PNG variants.

Maintenance utility only. It deliberately does not git-add or commit anything;
normal imports keep their stricter 10-PNG + index commit gate.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PIL import Image
import numpy as np

from import_asset_sheet import INDEX_PATH_NAME, INDEX_SCHEMA_VERSION, ROLES, save_index, sha256_file, signatures


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    assets: dict[str, object] = {}
    count = 0
    for role in ROLES:
        folder = repo_root / "assets" / role
        for path in sorted(folder.glob(f"{role}_[0-9][0-9].png")):
            rgba = np.asarray(Image.open(path).convert("RGBA"))
            relative = path.relative_to(repo_root).as_posix()
            set_number = path.stem.rsplit("_", 1)[-1]
            assets[relative] = {
                "role": role,
                "set": set_number,
                "sha256": sha256_file(path),
                **signatures(rgba[:, :, :3], rgba[:, :, 3]),
            }
            count += 1

    index = {
        "schema_version": INDEX_SCHEMA_VERSION,
        "sources": {},
        "assets": assets,
        "updated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "backfill_note": "Existing numbered assets indexed without original source-sheet hashes.",
    }
    path = save_index(repo_root, index)
    print(f"Indexed {count} installed numbered PNGs: {path.relative_to(repo_root)}")
    print("No git commit was created; review and commit this maintenance change manually.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
