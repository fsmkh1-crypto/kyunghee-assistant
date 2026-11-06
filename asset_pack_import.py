"""Add complete numbered image sets from a ZIP, never replace installed assets."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path
import re
import zipfile

from PIL import Image

ROLES = frozenset({"default", "cheer", "rest", "away", "warning", "leave",
                   "stats", "settings", "alert", "profile"})
NAME_PATTERN = re.compile(r"^(default|cheer|rest|away|warning|leave|stats|settings|alert|profile)_([0-9]{2})\.png$", re.I)
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PACK_BYTES = 250 * 1024 * 1024


@dataclass(frozen=True)
class ImportResult:
    sets: tuple[str, ...]
    added: int
    identical: int


def import_numbered_pack(zip_path: Path, asset_dir: Path) -> ImportResult:
    """Validate the entire pack first; exclusive writes and rollback preserve originals.

    Only two-digit numbered PNG names are considered. Sources may be inside a
    nested assets/role folder, but ZIP paths are never extracted or trusted.
    Canonical masters, settings, executables and manifests are never imported.
    """
    files: dict[tuple[str, str], bytes] = {}
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        if len(archive.infolist()) > 5000:
            raise ValueError("ZIP에 파일이 너무 많습니다. 이미지 세트 ZIP을 선택해 주세요.")
        for info in archive.infolist():
            name = info.filename.replace("\\", "/").rsplit("/", 1)[-1]
            match = NAME_PATTERN.fullmatch(name)
            if not match or info.is_dir():
                continue
            role, number = match.group(1).lower(), match.group(2)
            if number == "00":
                raise ValueError("세트 번호는 01~99만 사용할 수 있습니다.")
            if not 0 < info.file_size <= MAX_IMAGE_BYTES:
                raise ValueError("이미지 파일 크기를 확인해 주세요.")
            total += info.file_size
            if total > MAX_PACK_BYTES:
                raise ValueError("이미지 세트 ZIP이 너무 큽니다.")
            with archive.open(info) as source:
                content = source.read(MAX_IMAGE_BYTES + 1)
            if len(content) > MAX_IMAGE_BYTES:
                raise ValueError("이미지 파일 크기를 확인해 주세요.")
            key = (role, number)
            if key in files and files[key] != content:
                raise ValueError(f"ZIP 안에 서로 다른 {role}_{number}.png가 있습니다.")
            try:
                with Image.open(io.BytesIO(content)) as image:
                    if image.format != "PNG" or max(image.size) > 4000:
                        raise ValueError("지원하지 않는 이미지")
                    image.verify()
                with Image.open(io.BytesIO(content)) as image:
                    image.convert("RGBA").load()
            except Exception:
                raise ValueError(f"{role}_{number}.png 이미지를 읽을 수 없습니다.") from None
            files[key] = content
    if not files:
        raise ValueError("번호가 있는 PNG 세트를 찾지 못했습니다. 분할 배포본 대신 이미지 세트 ZIP을 선택해 주세요.")
    numbers = sorted({number for _role, number in files})
    for number in numbers:
        if {role for role, n in files if n == number} != ROLES:
            raise ValueError(f"세트 {number}에 10개 역할 이미지가 모두 필요합니다.")
    root = Path(asset_dir)
    if root.is_symlink():
        raise ValueError("연결된 에셋 폴더에는 가져올 수 없습니다.")
    pending = []
    identical = 0
    for (role, number), content in sorted(files.items()):
        folder = root / role
        target = folder / f"{role}_{number}.png"
        if folder.is_symlink() or target.is_symlink():
            raise ValueError("연결된 에셋 파일에는 가져올 수 없습니다.")
        if target.exists():
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
                raise ValueError(f"기존 {target.name}과 다릅니다. 원본을 보존하려고 가져오기를 중단했습니다.")
            identical += 1
        else:
            pending.append((target, content))
    created = []
    try:
        for target, content in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("xb") as output:
                created.append(target)
                output.write(content)
    except Exception:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return ImportResult(tuple(numbers), len(created), identical)
