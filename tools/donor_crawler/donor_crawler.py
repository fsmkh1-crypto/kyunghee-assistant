from __future__ import annotations

import argparse
import csv
import hashlib
import io
import mimetypes
import re
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
UA = "KyungheeAssistantDonorCollector/0.2 (+personal reference workflow)"

# Collection is intentionally broad. These markers only affect usage labels;
# explicit reuse/AI/derivative prohibitions are skipped automatically.
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


@dataclass
class Candidate:
    query: str
    page_url: str
    image_url: str
    source_domain: str
    license_state: str
    usage_state: str
    width: int
    height: int
    sha256: str
    mime_type: str
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


def extract_images(page_url: str, html: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    vals: list[str] = []
    for selector, attr in (("meta[property='og:image']", "content"), ("meta[name='twitter:image']", "content")):
        for node in soup.select(selector):
            v = node.get(attr)
            if isinstance(v, str) and v:
                vals.append(abs_url(page_url, v))
    for img in soup.find_all("img"):
        for attr in ("src", "data-src", "data-original", "data-lazy-src"):
            v = img.get(attr)
            if isinstance(v, str) and v and not v.startswith("data:"):
                vals.append(abs_url(page_url, v))
    out: list[str] = []
    for v in vals:
        if v.startswith("http") and v not in out:
            out.append(v)
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


def upload_bytes(drive, folder_id: str, name: str, data: bytes, mime: str, props: dict[str, str]):
    media = MediaIoBaseUpload(io.BytesIO(data), mimetype=mime, resumable=False)
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


def crawl(queries: Iterable[str], args) -> list[Candidate]:
    s = make_session()
    drive = None if args.dry_run else drive_service(args.client_secret, args.token)
    seen_hashes: set[str] = set()
    rows: list[Candidate] = []
    uploaded = 0

    for query in queries:
        if uploaded >= args.limit:
            break
        try:
            pages = ddg_search(s, query, args.pages_per_query)
        except Exception as exc:
            print(f"[search-failed] {query}: {exc}")
            continue

        for page_url in pages:
            if uploaded >= args.limit:
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

            domain = urllib.parse.urlsplit(page_url).netloc.lower().removeprefix("www.")
            for image_url in extract_images(page_url, html):
                if uploaded >= args.limit:
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

                row = Candidate(
                    query=query,
                    page_url=page_url,
                    image_url=image_url,
                    source_domain=domain,
                    license_state=license_state,
                    usage_state=usage_state,
                    width=width,
                    height=height,
                    sha256=digest,
                    mime_type=mime,
                    notes=note,
                )

                name = safe_name(domain, digest, mime)
                if args.dry_run:
                    print(f"[dry-run] {name} {width}x{height} {usage_state} <- {page_url}")
                else:
                    try:
                        created = upload_bytes(
                            drive,
                            args.drive_folder_id,
                            name,
                            data,
                            mime,
                            {
                                "sourceDomain": domain[:124],
                                "licenseState": license_state[:124],
                                "usageState": usage_state[:124],
                                "sha256": digest[:124],
                            },
                        )
                        row.drive_file_id = created.get("id", "")
                        row.drive_web_view_link = created.get("webViewLink", "")
                        uploaded += 1
                        print(f"[uploaded {uploaded}/{args.limit}] {name}")
                    except Exception as exc:
                        print(f"[upload-failed] {name}: {exc}")
                        continue
                rows.append(row)

    write_manifest(args.manifest, rows)
    print(f"done: uploaded={uploaded}, manifest_rows={len(rows)}, stop_limit={args.limit}")
    return rows


def parse_args():
    p = argparse.ArgumentParser(description="Collect web image references and upload a bounded set to Google Drive.")
    p.add_argument("--query", action="append", dest="queries", help="Search query. Repeatable.")
    p.add_argument("--queries-file", type=Path, help="UTF-8 file with one query per line.")
    p.add_argument("--limit", type=int, default=10, help="Hard stop after this many successful Drive uploads.")
    p.add_argument("--pages-per-query", type=int, default=15)
    p.add_argument("--min-width", type=int, default=700)
    p.add_argument("--min-height", type=int, default=700)
    p.add_argument("--max-bytes", type=int, default=15 * 1024 * 1024)
    p.add_argument("--drive-folder-id", default=DEFAULT_DRIVE_FOLDER_ID)
    p.add_argument("--client-secret", type=Path, default=Path("client_secret.json"))
    p.add_argument("--token", type=Path, default=Path(".secrets/drive_token.json"))
    p.add_argument("--manifest", type=Path, default=Path("donor_manifest.csv"))
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
        queries = [
            "adult female seated floor pose reference front view full body",
            "adult female sitting pose anatomy reference knees up",
            "female seated figure reference front low angle",
            "female anatomy seated pose reference",
            "female body pose reference sitting floor",
        ]
    args.limit = max(1, min(args.limit, 100))
    crawl(queries, args)


if __name__ == "__main__":
    main()
