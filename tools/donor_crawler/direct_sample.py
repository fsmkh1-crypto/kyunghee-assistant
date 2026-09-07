from __future__ import annotations

import argparse
import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from PIL import Image

UA = "KyungheeAssistantReferenceSampler/0.4"


@dataclass
class Row:
    source_id: str
    image_url: str
    width: int
    height: int
    sha256: str
    file_name: str


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    args.output_dir.mkdir(parents=True, exist_ok=True)
    rows: list[Row] = []
    seen: set[str] = set()

    for raw in args.list.read_text(encoding="utf-8").splitlines():
        if len(rows) >= args.limit:
            break
        raw = raw.strip()
        if not raw or raw.startswith("#"):
            continue
        parts = raw.split("\t", 1)
        if len(parts) != 2:
            continue
        source_id, url = parts
        try:
            r = session.get(url, timeout=20, allow_redirects=True)
            r.raise_for_status()
            data = r.content
            if not data or len(data) > 15_000_000:
                continue
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            with Image.open(io.BytesIO(data)) as im:
                im = im.convert("RGB")
                width, height = im.size
                im.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
                idx = len(rows) + 1
                name = f"candidate_{idx:02d}_pexels_{source_id}_{digest[:10]}.jpg"
                im.save(args.output_dir / name, "JPEG", quality=90, optimize=True)
            rows.append(Row(source_id, url, width, height, digest, name))
            print(f"[selected {len(rows)}/{args.limit}] {source_id} {width}x{height}")
        except Exception as exc:
            print(f"[failed] {source_id}: {exc}")

    with (args.output_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(Row.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    print(f"done: selected={len(rows)}")


if __name__ == "__main__":
    main()
