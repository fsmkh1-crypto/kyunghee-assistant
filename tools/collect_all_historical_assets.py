from __future__ import annotations

import csv
import json
import pathlib
import subprocess

ROOT = pathlib.Path("asset_archive")
ALL = ROOT / "ALL_UNIQUE"
CUR = ROOT / "CURRENT_CANONICAL"
HIST = ROOT / "HISTORICAL_ONLY"
EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
CANONICAL_REF = "origin/ui/dark-kyunghee-redesign"


def run(*args: str, text: bool = True):
    return subprocess.check_output(args, text=text)


def iter_images(ref: str):
    for line in run("git", "ls-tree", "-r", "--full-tree", ref).splitlines():
        meta, path = line.split("\t", 1)
        _mode, typ, sha = meta.split()
        if typ != "blob" or not path.startswith("assets/"):
            continue
        if pathlib.Path(path).suffix.lower() not in EXTS:
            continue
        yield path, sha


def main() -> None:
    for p in (ALL, CUR, HIST):
        p.mkdir(parents=True, exist_ok=True)

    blobs: dict[str, dict[str, set[str]]] = {}
    commits = run("git", "rev-list", "--all").splitlines()
    for commit in commits:
        for path, sha in iter_images(commit):
            rec = blobs.setdefault(sha, {"paths": set(), "commits": set()})
            rec["paths"].add(path)
            rec["commits"].add(commit)

    current = dict(iter_images(CANONICAL_REF))
    current_shas = set(current.values())

    manifest = []
    used_names: set[str] = set()
    for sha, rec in sorted(blobs.items()):
        paths = sorted(rec["paths"])
        first = paths[0]
        ext = pathlib.Path(first).suffix.lower()
        base = pathlib.Path(first).stem
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in base)[:80]
        name = f"{sha[:12]}__{safe}{ext}"
        if name in used_names:
            name = f"{sha}__{safe}{ext}"
        used_names.add(name)

        data = subprocess.check_output(["git", "cat-file", "blob", sha])
        (ALL / name).write_bytes(data)
        if sha not in current_shas:
            (HIST / name).write_bytes(data)

        manifest.append(
            {
                "blob_sha": sha,
                "size": len(data),
                "is_in_current_canonical": sha in current_shas,
                "first_path": first,
                "all_paths": paths,
                "commit_count": len(rec["commits"]),
                "commits": sorted(rec["commits"]),
                "archive_name": name,
            }
        )

    for path, sha in sorted(current.items()):
        out = CUR / path.removeprefix("assets/")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(subprocess.check_output(["git", "cat-file", "blob", sha]))

    summary = {
        "canonical_ref": CANONICAL_REF,
        "current_canonical_image_files": len(current),
        "current_canonical_unique_blobs": len(current_shas),
        "all_historical_unique_blobs": len(blobs),
        "historical_only_unique_blobs": len(set(blobs) - current_shas),
        "extensions": sorted(EXTS),
    }
    (ROOT / "SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (ROOT / "MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    with (ROOT / "MANIFEST.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "blob_sha",
                "size",
                "is_in_current_canonical",
                "first_path",
                "all_paths",
                "commit_count",
                "archive_name",
            ]
        )
        for m in manifest:
            w.writerow(
                [
                    m["blob_sha"],
                    m["size"],
                    m["is_in_current_canonical"],
                    m["first_path"],
                    " | ".join(m["all_paths"]),
                    m["commit_count"],
                    m["archive_name"],
                ]
            )

    readme = (
        "# Kyunghee Assistant Asset Archive\n\n"
        f"Canonical source branch: \`ui/dark-kyunghee-redesign\`\n\n"
        f"- Current canonical image files: {len(current)}\n"
        f"- Current canonical unique blobs: {len(current_shas)}\n"
        f"- All unique historical image blobs under \`assets/\`: {len(blobs)}\n"
        f"- Historical-only unique blobs: {len(set(blobs) - current_shas)}\n\n"
        "Folders:\n"
        "- \`CURRENT_CANONICAL/\`: exact current canonical branch image files.\n"
        "- \`ALL_UNIQUE/\`: every unique historical image blob under \`assets/\`.\n"
        "- \`HISTORICAL_ONLY/\`: blobs not present in the current canonical branch.\n"
        "- \`MANIFEST.json\` and \`MANIFEST.csv\`: SHA/path/commit provenance.\n"
    )
    (ROOT / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
