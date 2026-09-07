from __future__ import annotations

import argparse
import csv
import hashlib
import io
import mimetypes
import re
import shutil
import tempfile
import urllib.parse
import urllib.robotparser
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import requests
from bs4 import BeautifulSoup
from PIL import Image
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

SCOPES = ["https://www.googleapis.com/auth/drive.file"]
DEFAULT_DRIVE_FOLDER_ID = "1XhlBU1Koa5RhRrhPpHkBoOsT2yPdpr8a"  # GPT/donor_rest
UA = "KyungheeAssistantDonorCollector/0.4 (+personal reference workflow)"

FREE_MARKERS = (
    "cc0", "public domain", "cc by", "creative commons attribution",
    "pexels license", "free to use", "royalty-free",
)
RESTRICTED_MARKERS = (
    "all rights reserved", "no derivatives", "cc by-nd", "cc by-nc-nd",
    "do not redistribute", "no redistribution", "editorial use only",
    "noai", "may not use these resources for llms", "may not use these resources for ai",
)
GATED_MARKERS = (
    "sign in to download", "log in to download", "purchase to download",
    "subscribe to download", "members only",
)

POSITIVE_TERMS: tuple[tuple[str, int], ...] = (
    ("sitting", 4), ("seated", 4), ("floor", 3),
    ("full body", 4), ("full-body", 4), ("whole body", 4), ("full length", 3),
    ("knees up", 4), ("bent knees", 3), ("bent knee", 2),
    ("front view", 3), ("front-facing", 3), ("three quarter", 3), ("3/4", 3),
    ("low angle", 3), ("low viewpoint", 3),
    ("figure reference", 3), ("pose reference", 3), ("anatomy reference", 3),
    ("anatomy", 1), ("studio", 2), ("plain background", 2),
    ("turnaround", 5), ("multi-angle", 5), ("multi angle", 5), ("multiple angles", 5),
    ("lower body", 2), ("body proportions", 2),
)
NEGATIVE_TERMS: tuple[tuple[str, int], ...] = (
    ("thumbnail", 4), ("avatar", 4), ("icon", 4), ("logo", 4),
    ("banner", 3), ("sprite", 4), ("collage", 3), ("contact sheet", 2),
    ("watermark", 3), ("preview only", 2),
)


@dataclass
class Candidate:
    query: str
    page_url: str
    page_title: str
    image_url: str
    image_context: str
    source_domain: str
    license_state: str
    usage_state: str
    width: int
    height: int
    score: int
    score_reasons: str
    sha256: str
    mime_type: str
    local_name: str = ""
    drive_file_id: str = ""
    drive_web_view_link: str = ""
    notes: str = ""


def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.8"})
    return s


def robots_allows(s: requests.Session, url: str) -> bool:
    p = urllib.parse.urlsplit(url)
    if p.scheme not in ("http", "https"):
        return False
    robots = urllib.parse.urlunsplit((p.scheme, p.netloc, "/robots.txt", "", ""))
    rp = urllib.robotparser.RobotFileParser()
    try:
        r = s.get(robots, timeout=8)
        if r.ok:
            rp.parse(r.text.splitlines())
            return rp.can_fetch(UA, url)
    except requests.RequestException:
        pass
    return True


def ddg_search(s: requests.Session, query: str, limit: int) -> list[str]:
    r = s.get("https://html.duckduckgo.com/html/", params={"q": query}, timeout=25)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    out: list[str] = []
    for a in soup.select("a.result__a"):
        href = a.get("href")
        if not href:
            continue
        p = urllib.parse.urlsplit(href)
        target = urllib.parse.parse_qs(p.query).get("uddg", [href])[0]
        target = urllib.parse.unquote(target)
        if target.startswith("http") and target not in out:
            out.append(target)
        if len(out) >= limit:
            break
    return out


def classify_license(page_text: str) -> tuple[str, str, str]:
    t = re.sub(r"\s+", " ", page_text.lower())[:250000]
    if any(x in t for x in RESTRICTED_MARKERS):
        return "restricted", "skip", "explicit reuse/AI/derivative restriction detected"
    if any(x in t for x in GATED_MARKERS):
        return "unknown", "reference_only", "download appears gated; no gate bypass attempted"
    if any(x in t for x in FREE_MARKERS):
        return "explicit_free_or_permissive", "candidate", "permissive marker detected; verify exact terms before final app use"
    return "unknown", "reference_only", "no clear license marker found"


def abs_url(base: str, value: str) -> str:
    return urllib.parse.urljoin(base, value.strip())


def page_title(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    if soup.title and soup.title.string:
        return re.sub(r"\s+", " ", soup.title.string).strip()[:300]
    og = soup.select_one("meta[property='og:title']")
    if og and isinstance(og.get("content"), str):
        return re.sub(r"\s+", " ", og.get("content", "")).strip()[:300]
    return ""


def extract_images(page_url: str, html: str) -> list[tuple[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    vals: list[tuple[str, str]] = []
    for selector, attr in (("meta[property='og:image']", "content"), ("meta[name='twitter:image']", "content")):
        for node in soup.select(selector):
            v = node.get(attr)
            if isinstance(v, str) and v:
                vals.append((abs_url(page_url, v), "social preview image"))
    for img in soup.find_all("img"):
        context = " ".join(str(img.get(x, "")) for x in ("alt", "title", "aria-label") if img.get(x))
        context = re.sub(r"\s+", " ", context).strip()[:500]
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            v = img.get(attr)
            if isinstance(v, str) and v and not v.startswith("data:"):
                vals.append((abs_url(page_url, v), context))
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for url, context in vals:
        if url.startswith("http") and url not in seen:
            seen.add(url)
            out.append((url, context))
    return out


def download_image(s: requests.Session, url: str, max_bytes: int) -> tuple[bytes, str] | None:
    try:
        with s.get(url, timeout=25, stream=True, allow_redirects=True) as r:
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").split(";")[0].strip().lower()
            if ctype and not ctype.startswith("image/"):
                return None
            buf = io.BytesIO()
            for chunk in r.iter_content(128 * 1024):
                if chunk:
                    buf.write(chunk)
                    if buf.tell() > max_bytes:
                        return None
            data = buf.getvalue()
        with Image.open(io.BytesIO(data)) as im:
            im.verify()
        if not ctype:
            with Image.open(io.BytesIO(data)) as im:
                ctype = Image.MIME.get(im.format, "image/jpeg")
        return data, ctype
    except Exception:
        return None


def image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as im:
        return im.size


def score_candidate(query: str, title: str, context: str, page_url: str, image_url: str, width: int, height: int, usage_state: str) -> tuple[int, str]:
    text = " ".join((query, title, context, page_url, image_url)).lower()
    score = 0
    reasons: list[str] = []
    for term, weight in POSITIVE_TERMS:
        if term in text:
            score += weight
            reasons.append(f"+{weight}:{term}")
    for term, weight in NEGATIVE_TERMS:
        if term in text:
            score -= weight
            reasons.append(f"-{weight}:{term}")
    short = min(width, height)
    if short >= 2500:
        score += 7
        reasons.append("+7:2500px+")
    elif short >= 1600:
        score += 5
        reasons.append("+5:1600px+")
    elif short >= 1000:
        score += 3
        reasons.append("+3:1000px+")
    elif short >= 700:
        score += 1
        reasons.append("+1:700px+")
    ratio = width / max(height, 1)
    if 0.45 <= ratio <= 1.8:
        score += 2
        reasons.append("+2:usable-aspect")
    elif ratio < 0.3 or ratio > 2.5:
        score -= 3
        reasons.append("-3:extreme-aspect")
    if usage_state == "candidate":
        score += 2
        reasons.append("+2:permissive-marker")
    return score, ";".join(reasons[:24])


def drive_service(client_secret: Path, token_path: Path):
    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(client_secret), SCOPES)
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json(), encoding="utf-8")
    return build("drive", "v3", credentials=creds)


def upload_file(drive, folder_id: str, name: str, path: Path, mime: str, props: dict[str, str]):
    media = MediaIoBaseUpload(path.open("rb"), mimetype=mime, resumable=False)
    meta = {"name": name, "parents": [folder_id], "appProperties": props}
    return drive.files().create(body=meta, media_body=media, fields="id,webViewLink,name").execute()


def safe_name(domain: str, digest: str, mime: str) -> str:
    ext = mimetypes.guess_extension(mime) or ".img"
    if ext == ".jpe":
        ext = ".jpg"
    domain = re.sub(r"[^a-zA-Z0-9._-]+", "_", domain)[:50]
    return f"{domain}_{digest[:14]}{ext}"


def write_manifest(path: Path, rows: list[Candidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as f:
        fields = list(Candidate.__dataclass_fields__.keys())
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for row in rows:
            w.writerow(asdict(row))


def export_preview(src: Path, dst: Path, max_side: int, quality: int) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
        im.save(dst, "JPEG", quality=quality, optimize=True)


def crawl(queries: Iterable[str], args) -> list[Candidate]:
    s = make_session()
    drive = None if args.dry_run else drive_service(args.client_secret, args.token)
    seen_hashes: set[str] = set()
    selected_rows: list[Candidate] = []
    staged: list[tuple[Candidate, Path]] = []

    with tempfile.TemporaryDirectory(prefix="donor-crawler-") as temp_root:
        temp_root_path = Path(temp_root)
        for query in queries:
            if len(staged) >= args.candidate_pool:
                break
            try:
                pages = ddg_search(s, query, args.pages_per_query)
            except Exception as exc:
                print(f"[search-failed] {query}: {exc}")
                continue
            accepted_this_query = 0
            for page_url in pages:
                if len(staged) >= args.candidate_pool or accepted_this_query >= args.candidates_per_query:
                    break
                if not robots_allows(s, page_url):
                    print(f"[robots-skip] {page_url}")
                    continue
                try:
                    r = s.get(page_url, timeout=20, allow_redirects=True)
                    r.raise_for_status()
                    html = r.text
                except requests.RequestException as exc:
                    print(f"[page-failed] {page_url}: {exc}")
                    continue
                license_state, usage_state, note = classify_license(html)
                if usage_state == "skip":
                    print(f"[rights-skip] {page_url}")
                    continue
                title = page_title(html)
                domain = urllib.parse.urlsplit(page_url).netloc.lower().removeprefix("www.")
                page_images = extract_images(page_url, html)[: args.images_per_page]
                for image_url, context in page_images:
                    if len(staged) >= args.candidate_pool or accepted_this_query >= args.candidates_per_query:
                        break
                    got = download_image(s, image_url, args.max_bytes)
                    if not got:
                        continue
                    data, mime = got
                    digest = hashlib.sha256(data).hexdigest()
                    if digest in seen_hashes:
                        continue
                    seen_hashes.add(digest)
                    try:
                        width, height = image_size(data)
                    except Exception:
                        continue
                    if width < args.min_width or height < args.min_height:
                        continue
                    score, score_reasons = score_candidate(query, title, context, page_url, image_url, width, height, usage_state)
                    row = Candidate(
                        query=query,
                        page_url=page_url,
                        page_title=title,
                        image_url=image_url,
                        image_context=context,
                        source_domain=domain,
                        license_state=license_state,
                        usage_state=usage_state,
                        width=width,
                        height=height,
                        score=score,
                        score_reasons=score_reasons,
                        sha256=digest,
                        mime_type=mime,
                        notes=note,
                    )
                    staged_path = temp_root_path / f"{digest}.bin"
                    staged_path.write_bytes(data)
                    staged.append((row, staged_path))
                    accepted_this_query += 1
                    print(f"[staged {len(staged)}/{args.candidate_pool}] score={score} {width}x{height} <- {page_url}")

        ranked = sorted(staged, key=lambda item: (item[0].score, min(item[0].width, item[0].height)), reverse=True)
        print(f"[ranking] staged={len(ranked)} select_limit={args.limit}")
        if args.output_dir:
            args.output_dir.mkdir(parents=True, exist_ok=True)

        for rank, (row, staged_path) in enumerate(ranked, 1):
            if len(selected_rows) >= args.limit:
                break
            base_name = safe_name(row.source_domain, row.sha256, row.mime_type)
            local_name = f"candidate_{len(selected_rows)+1:02d}_{Path(base_name).stem}.jpg"

            if args.output_dir:
                preview_path = args.output_dir / local_name
                export_preview(staged_path, preview_path, args.preview_max_side, args.preview_quality)
                row.local_name = local_name

            if args.dry_run:
                selected_rows.append(row)
                print(f"[top {len(selected_rows)}] rank={rank} score={row.score} {row.width}x{row.height} {row.usage_state} <- {row.page_url}")
                continue

            try:
                created = upload_file(
                    drive,
                    args.drive_folder_id,
                    base_name,
                    staged_path,
                    row.mime_type,
                    {
                        "sourceDomain": row.source_domain[:124],
                        "licenseState": row.license_state[:124],
                        "usageState": row.usage_state[:124],
                        "sha256": row.sha256[:124],
                        "score": str(row.score)[:124],
                    },
                )
                row.drive_file_id = created.get("id", "")
                row.drive_web_view_link = created.get("webViewLink", "")
                selected_rows.append(row)
                print(f"[uploaded {len(selected_rows)}/{args.limit}] rank={rank} score={row.score} {base_name}")
            except Exception as exc:
                print(f"[upload-failed] {base_name}: {exc}")
                continue

    write_manifest(args.manifest, selected_rows)
    print(f"done: selected={len(selected_rows)}, stop_limit={args.limit}, dry_run={args.dry_run}")
    return selected_rows


def parse_args():
    p = argparse.ArgumentParser(description="Collect broad web pose/image references, rank them, and upload a bounded set to Google Drive.")
    p.add_argument("--query", action="append", dest="queries", help="Search query. Repeatable.")
    p.add_argument("--queries-file", type=Path, help="UTF-8 file with one query per line.")
    p.add_argument("--limit", type=int, default=10, help="Hard stop after this many successful selections/uploads.")
    p.add_argument("--candidate-pool", type=int, default=60, help="Maximum number of valid unique candidates staged before ranking.")
    p.add_argument("--candidates-per-query", type=int, default=4, help="Maximum staged candidates contributed by one query.")
    p.add_argument("--pages-per-query", type=int, default=12)
    p.add_argument("--images-per-page", type=int, default=5)
    p.add_argument("--min-width", type=int, default=700)
    p.add_argument("--min-height", type=int, default=700)
    p.add_argument("--max-bytes", type=int, default=10 * 1024 * 1024)
    p.add_argument("--drive-folder-id", default=DEFAULT_DRIVE_FOLDER_ID)
    p.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    p.add_argument("--token", type=Path, default=Path(".secrets/drive_token.json"))
    p.add_argument("--manifest", type=Path, default=Path("donor_manifest.csv"))
    p.add_argument("--output-dir", type=Path, help="Optional directory for selected JPEG previews; useful for CI verification.")
    p.add_argument("--preview-max-side", type=int, default=1600)
    p.add_argument("--preview-quality", type=int, default=88)
    p.add_argument("--dry-run", action="store_true")
    return p.parse_args()


def main():
    args = parse_args()
    queries = list(args.queries or [])
    if args.queries_file:
        queries.extend(
            line.strip() for line in args.queries_file.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        )
    if not queries:
        default_queries = Path(__file__).with_name("queries.txt")
        if default_queries.exists():
            queries = [
                line.strip() for line in default_queries.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.lstrip().startswith("#")
            ]
    if not queries:
        queries = [
            "female seated pose reference full body",
            "woman sitting on floor studio full body",
            "female floor sitting pose reference",
        ]
    args.limit = max(1, min(args.limit, 100))
    args.candidate_pool = max(args.limit, min(args.candidate_pool, 300))
    args.candidates_per_query = max(1, min(args.candidates_per_query, 20))
    args.images_per_page = max(1, min(args.images_per_page, 20))
    args.preview_max_side = max(640, min(args.preview_max_side, 3000))
    args.preview_quality = max(60, min(args.preview_quality, 95))
    crawl(queries, args)


if __name__ == "__main__":
    main()
