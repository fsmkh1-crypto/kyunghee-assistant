from __future__ import annotations

import argparse
import csv
import hashlib
import io
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup
from PIL import Image

UA = "KyungheeAssistantReferenceSampler/0.3"


@dataclass
class Row:
    page_url: str
    title: str
    image_url: str
    source_domain: str
    width: int
    height: int
    file_name: str


def extract(page_url: str, html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    title = ""
    if soup.title and soup.title.string:
        title = " ".join(soup.title.string.split())[:300]
    for selector in ("meta[property='og:image']", "meta[name='twitter:image']"):
        node = soup.select_one(selector)
        if node:
            value = node.get("content")
            if isinstance(value, str) and value:
                return title, urljoin(page_url, value)
    for img in soup.find_all("img"):
        value = img.get("src")
        if isinstance(value, str) and value.startswith("http"):
            return title, value
    return title, ""


def download(session: requests.Session, url: str) -> bytes | None:
    try:
        r = session.get(url, timeout=12, allow_redirects=True)
        r.raise_for_status()
        if len(r.content) > 12_000_000:
            return None
        with Image.open(io.BytesIO(r.content)) as im:
            im.verify()
        return r.content
    except Exception as exc:
        print(f"[image-failed] {url}: {exc}")
        return None


def save_jpeg(data: bytes, path: Path) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        im = im.convert("RGB")
        w, h = im.size
        im.thumbnail((1800, 1800), Image.Resampling.LANCZOS)
        im.save(path, "JPEG", quality=90, optimize=True)
        return w, h


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages-file", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    pages = [x.strip() for x in args.pages_file.read_text(encoding="utf-8").splitlines() if x.strip() and not x.startswith("#")]
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    args.output_dir.mkdir(parents=True, exist_ok=True)

    rows: list[Row] = []
    seen: set[str] = set()
    for page_url in pages:
        if len(rows) >= args.limit:
            break
        try:
            r = session.get(page_url, timeout=12, allow_redirects=True)
            r.raise_for_status()
        except Exception as exc:
            print(f"[page-failed] {page_url}: {exc}")
            continue
        title, image_url = extract(page_url, r.text)
        if not image_url:
            print(f"[no-image] {page_url}")
            continue
        data = download(session, image_url)
        if not data:
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest in seen:
            continue
        seen.add(digest)
        idx = len(rows) + 1
        name = f"candidate_{idx:02d}_{digest[:12]}.jpg"
        try:
            width, height = save_jpeg(data, args.output_dir / name)
        except Exception as exc:
            print(f"[save-failed] {image_url}: {exc}")
            continue
        domain = urlsplit(page_url).netloc.lower().removeprefix("www.")
        rows.append(Row(page_url, title, image_url, domain, width, height, name))
        print(f"[selected {idx}/{args.limit}] {width}x{height} {title[:80]}")

    with (args.output_dir / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=list(Row.__dataclass_fields__.keys()))
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))

    print(f"done: selected={len(rows)}")


if __name__ == "__main__":
    main()
