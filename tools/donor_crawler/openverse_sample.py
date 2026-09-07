from __future__ import annotations

import argparse
import csv
import hashlib
import io
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import requests
from PIL import Image

API = "https://api.openverse.org/v1/images/"
UA = "KyungheeAssistantReferenceSampler/0.2"

POS = (
    ("sitting", 5), ("seated", 5), ("floor", 4), ("full body", 5),
    ("full length", 4), ("knees up", 5), ("bent knee", 3), ("front", 3),
    ("three quarter", 3), ("low angle", 3), ("pose", 2), ("anatomy", 2),
    ("figure", 2), ("studio", 2), ("turnaround", 6), ("multi angle", 6),
    ("lower body", 3), ("legs", 2), ("knee", 2),
)
OBSTRUCTION = (
    ("long dress", 7), ("gown", 6), ("long skirt", 6), ("maxi dress", 7),
    ("jeans", 5), ("trousers", 5), ("pants", 4), ("coat", 5),
    ("jacket", 4), ("robe", 5), ("blanket", 7), ("armor", 6),
)


@dataclass
class Row:
    query: str
    title: str
    creator: str
    source: str
    landing_url: str
    original_url: str
    thumbnail_url: str
    license: str
    license_version: str
    width: int
    height: int
    score: int
    reasons: str
    file_name: str = ""


def text_context(item: dict) -> str:
    parts = [str(item.get(k) or "") for k in ("title", "creator", "category", "source", "provider")]
    tags = item.get("tags")
    if isinstance(tags, list):
        for tag in tags[:40]:
            if isinstance(tag, dict):
                parts.append(str(tag.get("name") or ""))
            elif isinstance(tag, str):
                parts.append(tag)
    return re.sub(r"\s+", " ", " ".join(parts)).strip().lower()


def score(query: str, item: dict) -> tuple[int, str]:
    text = (query + " " + text_context(item)).lower()
    total = 0
    reasons: list[str] = []
    for term, weight in POS:
        if term in text:
            total += weight
            reasons.append(f"+{weight}:{term}")
    penalty = 0
    for term, weight in OBSTRUCTION:
        if term in text:
            penalty += weight
            reasons.append(f"-{weight}:obstruction:{term}")
    total -= min(penalty, 18)
    try:
        w = int(item.get("width") or 0)
        h = int(item.get("height") or 0)
    except Exception:
        w = h = 0
    short = min(w, h) if w and h else 0
    if short >= 3000:
        total += 8; reasons.append("+8:3000px+")
    elif short >= 2200:
        total += 6; reasons.append("+6:2200px+")
    elif short >= 1600:
        total += 5; reasons.append("+5:1600px+")
    elif short >= 1000:
        total += 3; reasons.append("+3:1000px+")
    lic = str(item.get("license") or "").lower()
    if lic in {"cc0", "pdm", "by", "by-sa"}:
        total += 3; reasons.append("+3:clear-license")
    return total, ";".join(reasons[:24])


def search(session: requests.Session, query: str, size: int) -> list[dict]:
    r = session.get(API, params={"q": query, "page_size": size, "mature": "false"}, timeout=12)
    r.raise_for_status()
    data = r.json()
    results = [x for x in data.get("results", []) if isinstance(x, dict)]
    print(f"[search] {query!r}: {len(results)} results")
    return results


def download_preview(session: requests.Session, urls: list[str], max_bytes: int = 5_000_000) -> bytes | None:
    for url in urls:
        if not url.startswith("http"):
            continue
        try:
            with session.get(url, timeout=8, stream=True, allow_redirects=True) as r:
                r.raise_for_status()
                ctype = (r.headers.get("content-type") or "").lower()
                if ctype and "image" not in ctype:
                    continue
                buf = io.BytesIO()
                for chunk in r.iter_content(65536):
                    if chunk:
                        buf.write(chunk)
                        if buf.tell() > max_bytes:
                            raise ValueError("image too large")
                data = buf.getvalue()
            with Image.open(io.BytesIO(data)) as im:
                im.verify()
            return data
        except Exception:
            continue
    return None


def save_jpeg(data: bytes, path: Path, max_side: int = 1600) -> None:
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        im.save(path, "JPEG", quality=88, optimize=True)


def row_from_item(query: str, item: dict) -> Row | None:
    thumb = str(item.get("thumbnail") or "")
    original = str(item.get("url") or "")
    if not thumb.startswith("http") and not original.startswith("http"):
        return None
    try:
        w = int(item.get("width") or 0)
        h = int(item.get("height") or 0)
    except Exception:
        w = h = 0
    s, reasons = score(query, item)
    return Row(
        query=query,
        title=str(item.get("title") or "")[:300],
        creator=str(item.get("creator") or "")[:300],
        source=str(item.get("source") or item.get("provider") or "")[:120],
        landing_url=str(item.get("foreign_landing_url") or item.get("detail_url") or ""),
        original_url=original,
        thumbnail_url=thumb,
        license=str(item.get("license") or ""),
        license_version=str(item.get("license_version") or ""),
        width=w,
        height=h,
        score=s,
        reasons=reasons,
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries-file", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=10)
    ap.add_argument("--pool", type=int, default=40)
    ap.add_argument("--per-query", type=int, default=10)
    args = ap.parse_args()

    queries = [x.strip() for x in args.queries_file.read_text(encoding="utf-8").splitlines() if x.strip() and not x.lstrip().startswith("#")]
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})

    pool: dict[str, Row] = {}
    for query in queries:
        if len(pool) >= args.pool:
            break
        try:
            items = search(session, query, args.per_query)
        except Exception as exc:
            print(f"[search-failed] {query}: {exc}")
            continue
        for item in items:
            if len(pool) >= args.pool:
                break
            key = str(item.get("id") or item.get("url") or item.get("thumbnail") or "")
            if not key or key in pool:
                continue
            row = row_from_item(query, item)
            if not row:
                continue
            pool[key] = row
            print(f"[meta {len(pool)}/{args.pool}] score={row.score} {row.title[:70]}")

    ranked = sorted(pool.values(), key=lambda x: (x.score, min(x.width, x.height)), reverse=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    selected: list[Row] = []
    for rank, row in enumerate(ranked, 1):
        if len(selected) >= args.limit:
            break
        data = download_preview(session, [row.thumbnail_url, row.original_url])
        if not data:
            print(f"[download-skip] rank={rank} {row.title[:70]}")
            continue
        try:
            with Image.open(io.BytesIO(data)) as im:
                pw, ph = im.size
        except Exception:
            continue
        if min(pw, ph) < 250:
            continue
        digest = hashlib.sha256(data).hexdigest()[:12]
        idx = len(selected) + 1
        name = f"candidate_{idx:02d}_{digest}.jpg"
        save_jpeg(data, args.output_dir / name)
        row.file_name = name
        selected.append(row)
        print(f"[selected {idx}/{args.limit}] rank={rank} score={row.score} {row.title[:80]}")

    with (args.output_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(Row.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in selected:
            writer.writerow(asdict(row))

    print(f"done: pool={len(pool)} selected={len(selected)}")


if __name__ == "__main__":
    main()
