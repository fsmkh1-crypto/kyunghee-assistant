"""Import complete PNG role sets from a ZIP without replacing installed artwork."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import io
from pathlib import Path, PurePosixPath
import re
import stat
import json
import os
import tempfile
import zipfile

from PIL import Image

ROLES = frozenset({"default", "cheer", "rest", "away", "warning", "leave",
                   "stats", "settings", "alert", "profile"})
NAME_PATTERN = re.compile(r"^(default|cheer|rest|away|warning|leave|stats|settings|alert|profile)_([0-9]{2})\.png$", re.I)
CANONICAL_ALIASES = {
    "main_kyunghee.png": "default",
    "focus_cheer_kyunghee.png": "cheer",
    "rest_suggest_kyunghee.png": "rest",
    "away_kyunghee.png": "away",
    "warning_kyunghee.png": "warning",
    "leave_work_kyunghee.png": "leave",
    "stats_kyunghee.png": "stats",
    "settings_kyunghee.png": "settings",
    "alert_kyunghee.png": "alert",
    "profile_kyunghee.png": "profile",
}
MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PACK_BYTES = 250 * 1024 * 1024


@dataclass(frozen=True)
class ImportResult:
    sets: tuple[str, ...]
    added: int
    identical: int
    auto_assigned: tuple[str, ...] = ()
    reused: tuple[str, ...] = ()


@dataclass(frozen=True)
class _Candidate:
    info: zipfile.ZipInfo
    role: str
    number: str | None
    group: str
    kind: str
    parent_role: str | None


def _label(value: str) -> str:
    """Keep archive-controlled labels short and readable in the desktop dialog."""
    clean = "".join(character for character in value if character.isprintable())
    return clean if len(clean) <= 160 else clean[:157] + "..."


def _candidate(info: zipfile.ZipInfo) -> _Candidate | None:
    if info.is_dir():
        return None
    path = PurePosixPath(info.filename.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or (path.parts and ":" in path.parts[0]):
        if path.suffix.lower() == ".png":
            raise ValueError("ZIP 이미지 경로가 안전하지 않습니다.")
        return None
    name = path.name.lower()
    parent_role = path.parent.name.lower()
    parent_role = parent_role if parent_role in ROLES else None
    # A role directory describes one slot; its parent describes the whole pack.
    group = str(path.parent.parent if parent_role else path.parent)
    match = NAME_PATTERN.fullmatch(name)
    if match:
        return _Candidate(info, match[1].lower(), match[2], group, "numbered", parent_role)
    if name.endswith(".png") and name[:-4] in ROLES:
        return _Candidate(info, name[:-4], None, group, "role", parent_role)
    if name in CANONICAL_ALIASES:
        return _Candidate(info, CANONICAL_ALIASES[name], None, group, "alias", parent_role)
    if name == "image.png" and parent_role:
        return _Candidate(info, parent_role, None, group, "folder", parent_role)
    return None


def _read_png(archive: zipfile.ZipFile, candidate: _Candidate) -> bytes:
    info = candidate.info
    if stat.S_ISLNK(info.external_attr >> 16):
        raise ValueError(f"ZIP 안의 연결된 이미지 파일은 사용할 수 없습니다: {_label(info.filename)}")
    if not 0 < info.file_size <= MAX_IMAGE_BYTES:
        raise ValueError(f"이미지 파일 크기를 확인해 주세요: {_label(info.filename)}")
    try:
        with archive.open(info) as source:
            content = source.read(MAX_IMAGE_BYTES + 1)
        if len(content) != info.file_size or len(content) > MAX_IMAGE_BYTES:
            raise ValueError("이미지 크기 불일치")
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "PNG" or not all(0 < value <= 4000 for value in image.size):
                raise ValueError("지원하지 않는 이미지")
            image.verify()
        with Image.open(io.BytesIO(content)) as image:
            image.convert("RGBA").load()
    except Exception:
        raise ValueError(f"{_label(info.filename)} 이미지를 읽을 수 없습니다.") from None
    return content


def _missing_roles(roles: set[str], label: str) -> None:
    missing = sorted(ROLES - roles)
    if missing:
        raise ValueError(f"{label}에 10개 역할 이미지가 모두 필요합니다. 빠진 역할: {', '.join(missing)}")


def _is_link(path: Path) -> bool:
    return path.is_symlink() or getattr(path, "is_junction", lambda: False)()


def _validate_destination(root: Path) -> None:
    for path in (root, *root.parents):
        if _is_link(path):
            raise ValueError("연결된 에셋 폴더에는 가져올 수 없습니다.")
        if path.exists() and not path.is_dir():
            raise ValueError(f"에셋 폴더 경로가 폴더가 아닙니다: {path.name}")
    for role in ROLES:
        folder = root / role
        if _is_link(folder):
            raise ValueError("연결된 에셋 폴더에는 가져올 수 없습니다.")
        if folder.exists() and not folder.is_dir():
            raise ValueError(f"역할 폴더 경로가 폴더가 아닙니다: {role}")


def _occupied_numbers(root: Path) -> set[str]:
    occupied = set()
    for role in ROLES:
        folder = root / role
        if folder.is_dir():
            for path in folder.iterdir():
                match = NAME_PATTERN.fullmatch(path.name)
                if match and match[2] != "00":
                    # Even one file, directory or link reserves a number.
                    occupied.add(match[2])
    return occupied


def _fingerprint(files: dict[str, bytes]) -> tuple[bytes, ...]:
    return tuple(hashlib.sha256(files[role]).digest() for role in sorted(ROLES))


def _matching_installed_set(root: Path, numbers: set[str], files: dict[str, bytes]) -> str | None:
    for number in sorted(numbers):
        for role in sorted(ROLES):
            target = root / role / f"{role}_{number}.png"
            if _is_link(target) or not target.is_file():
                break
            if target.stat().st_size != len(files[role]):
                break
            if hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(files[role]).digest():
                break
        else:
            return number
    return None


def import_numbered_pack(zip_path: Path, asset_dir: Path, *, dry_run: bool = False) -> ImportResult:
    """Validate all groups, then add static role/role_NN.png destinations only.

    Numbered filenames keep their explicit numbers. Complete unnumbered groups
    accept role.png, approved canonical aliases, or role/Image.png. Grouping by
    their common pack folder prevents partial packs from being silently merged.
    Distinct complete groups may coexist with numbered sets; ambiguous mixed
    groups fail. Legacy canonical fallbacks alongside numbered files are ignored.
    Unnumbered groups reuse a byte-identical installed complete set, or receive
    the lowest free number in 01..99, including partial installed sets as occupied.
    ZIP members are read, never extracted; masters and the source ZIP are untouched.
    """
    numbered: dict[tuple[str, str], bytes] = {}
    unnumbered: dict[str, dict[str, bytes]] = {}
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > 5000:
            raise ValueError("ZIP에 파일이 너무 많습니다. 이미지 세트 ZIP을 선택해 주세요.")
        candidates = [candidate for info in infos if (candidate := _candidate(info)) is not None]
        explicit = [candidate for candidate in candidates if candidate.number is not None]
        explicit_groups = {candidate.group for candidate in explicit}
        numbered_groups: dict[str, dict[str, set[str]]] = {}
        for candidate in explicit:
            numbered_groups.setdefault(candidate.number, {}).setdefault(candidate.group, set()).add(candidate.role)
        for number, groups_for_number in numbered_groups.items():
            if not any(roles == ROLES for roles in groups_for_number.values()):
                complete_roles = set().union(*groups_for_number.values())
                if complete_roles == ROLES:
                    raise ValueError(f'세트 {number}의 역할 이미지가 서로 다른 폴더에 나뉘어 있습니다. 각 폴더에 완전한 10개 역할 세트가 필요합니다.')
        groups: dict[str, list[_Candidate]] = {}
        for candidate in candidates:
            if candidate.number is None:
                groups.setdefault(candidate.group, []).append(candidate)
        selected = list(explicit)
        for group, members in groups.items():
            aliases_only = all(member.kind == "alias" for member in members)
            if explicit and aliases_only:
                # Old numbered ZIPs often carry canonical fallback masters too.
                continue
            if group in explicit_groups:
                raise ValueError(
                    f"같은 폴더({_label(group)})에 번호형과 번호 없는 이미지가 섞여 있습니다. "
                    "각 세트를 별도 폴더나 ZIP으로 구분해 주세요."
                )
            selected.extend(members)
        if not selected:
            required = ", ".join(f"{role}.png" for role in sorted(ROLES))
            raise ValueError(
                "지원하는 PNG 역할 세트를 찾지 못했습니다. 필요한 이름: " + required +
                ". 번호형 <역할>_01.png 또는 각 역할 폴더의 Image.png도 사용할 수 있습니다."
            )
        for candidate in selected:
            if candidate.number == "00":
                raise ValueError("세트 번호는 01~99만 사용할 수 있습니다.")
            if candidate.number is None and candidate.parent_role not in (None, candidate.role):
                raise ValueError(f"파일 이름과 역할 폴더가 서로 다릅니다: {_label(candidate.info.filename)}")
            total += candidate.info.file_size
            if total > MAX_PACK_BYTES:
                raise ValueError("이미지 세트 ZIP이 너무 큽니다.")
            content = _read_png(archive, candidate)
            if candidate.number is not None:
                key = (candidate.role, candidate.number)
                previous = numbered.get(key)
                if previous is not None and previous != content:
                    raise ValueError(f"ZIP 안에 서로 다른 {candidate.role}_{candidate.number}.png가 있습니다.")
                numbered[key] = content
            else:
                group_files = unnumbered.setdefault(candidate.group, {})
                previous = group_files.get(candidate.role)
                if previous is not None and previous != content:
                    raise ValueError(f"폴더({_label(candidate.group)})에 서로 다른 {candidate.role} 역할 이미지가 있습니다.")
                group_files[candidate.role] = content
    numbers = {number for _role, number in numbered}
    for number in sorted(numbers):
        _missing_roles({role for role, n in numbered if n == number}, f"세트 {number}")
    for group, files in sorted(unnumbered.items()):
        _missing_roles(set(files), f"번호 없는 세트 폴더({_label(group)})")

    root = Path(asset_dir).absolute()
    _validate_destination(root)
    installed_numbers = _occupied_numbers(root)
    occupied = installed_numbers | numbers
    auto_assigned = set()
    reused = set()
    # A mixed ZIP may contain the same whole set both with and without numbers.
    unnumbered_choices: dict[tuple[bytes, ...], str] = {}
    for number in sorted(numbers):
        files = {role: numbered[(role, number)] for role in ROLES}
        unnumbered_choices.setdefault(_fingerprint(files), number)
    for group, files in sorted(unnumbered.items()):
        fingerprint = _fingerprint(files)
        number = unnumbered_choices.get(fingerprint)
        if number is not None and number not in auto_assigned:
            reused.add(number)
        if number is None:
            number = _matching_installed_set(root, installed_numbers, files)
            if number is not None:
                reused.add(number)
            else:
                number = next((f"{value:02}" for value in range(1, 100) if f"{value:02}" not in occupied), None)
                if number is None:
                    raise ValueError("01~99 세트 번호가 모두 사용 중입니다. 기존 이미지는 덮어쓰지 않습니다.")
                occupied.add(number)
                auto_assigned.add(number)
            unnumbered_choices[fingerprint] = number
        for role, content in files.items():
            key = (role, number)
            if key in numbered and numbered[key] != content:
                raise ValueError(f"ZIP의 번호형 세트 {number}와 재사용할 기존 세트 내용이 다릅니다.")
            numbered[key] = content
        numbers.add(number)

    pending = []
    identical = 0
    for (role, number), content in sorted(numbered.items()):
        target = root / role / f"{role}_{number}.png"
        if _is_link(target):
            raise ValueError("연결된 에셋 파일에는 가져올 수 없습니다.")
        if target.exists():
            if not target.is_file() or hashlib.sha256(target.read_bytes()).digest() != hashlib.sha256(content).digest():
                raise ValueError(f"기존 {target.name}과 다릅니다. 원본을 보존하려고 가져오기를 중단했습니다.")
            identical += 1
        else:
            pending.append((target, content))
    if dry_run:
        return ImportResult(tuple(sorted(numbers)), len(pending), identical,
                            tuple(sorted(auto_assigned)), tuple(sorted(reused)))
    created = []
    try:
        for target, content in pending:
            target.parent.mkdir(parents=True, exist_ok=True)
            _validate_destination(root)
            if _is_link(target):
                raise ValueError("연결된 에셋 파일에는 가져올 수 없습니다.")
            with target.open("xb") as output:
                created.append(target)
                output.write(content)
    except Exception:
        for target in reversed(created):
            target.unlink(missing_ok=True)
        raise
    return ImportResult(tuple(sorted(numbers)), len(created), identical,
                        tuple(sorted(auto_assigned)), tuple(sorted(reused)))


def preview_numbered_pack(zip_path: Path, asset_dir: Path) -> ImportResult:
    """Decode and check the complete plan without creating destination files."""
    return import_numbered_pack(zip_path, asset_dir, dry_run=True)


def adopt_legacy_imports(installation_root: Path, profile_root: Path) -> dict:
    """Copy non-shipped complete sets to the profile, preserving every original.

    The shipped asset index defines built-ins. Unknown or altered complete sets
    are adopted, with conflicts reported rather than replacing profile artwork.
    """
    from asset_rotation import raw_complete_sets
    from image_catalog import valid_image
    source, destination = Path(installation_root), Path(profile_root)
    marker = destination / 'asset_pack_adoption.json'
    _validate_destination(destination.absolute())
    if _is_link(marker):
        raise ValueError('연결된 마이그레이션 기록에는 쓸 수 없습니다.')
    source_signature = []
    for number in raw_complete_sets(source):
        for role in sorted(ROLES):
            path = source / role / f'{role}_{number:02d}.png'
            stat_result = path.stat()
            source_signature.append([path.relative_to(source).as_posix(), stat_result.st_mtime_ns, stat_result.st_size])
    if marker.is_file():
        try:
            saved = json.loads(marker.read_text(encoding='utf-8'))
            if isinstance(saved, dict) and saved.get('source_signature') == source_signature:
                return saved
        except (OSError, ValueError):
            pass
    try:
        index = json.loads((source / 'asset_index.json').read_text(encoding='utf-8'))['assets']
    except (OSError, ValueError, KeyError):
        # Without a trusted baseline do not misclassify installed assets.
        return {'schema_version': 1, 'copied': [], 'reused': [], 'conflicts': []}
    result = {'schema_version': 1, 'copied': [], 'reused': [], 'conflicts': [], 'source_signature': source_signature}
    for number in raw_complete_sets(source):
        files = {role: source / role / f'{role}_{number:02d}.png' for role in ROLES}
        if not all(valid_image(path) for path in files.values()):
            continue
        shipped = all(
            index.get('assets/' + path.relative_to(source).as_posix(), {}).get('sha256')
            == hashlib.sha256(path.read_bytes()).hexdigest() for path in files.values()
        )
        if shipped:
            continue
        try:
            with tempfile.TemporaryDirectory(prefix='seunga-adopt-') as temporary:
                archive_path = Path(temporary) / 'legacy.zip'
                with zipfile.ZipFile(archive_path, 'w') as archive:
                    for role, path in files.items():
                        archive.write(path, f'{role}/{role}_{number:02d}.png')
                imported = import_numbered_pack(archive_path, destination)
            result['copied' if imported.added else 'reused'].append(f'{number:02d}')
        except (OSError, ValueError, zipfile.BadZipFile):
            result['conflicts'].append(f'{number:02d}')
    destination.mkdir(parents=True, exist_ok=True)
    temporary = marker.with_suffix('.tmp')
    try:
        temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def preview_role_images(zip_path: Path) -> tuple[tuple[str, Image.Image], ...]:
    """Bounded thumbnail previews; only call after the complete dry-run validates."""
    previews = {}
    with zipfile.ZipFile(zip_path) as archive:
        candidates = [candidate for info in archive.infolist() if (candidate := _candidate(info)) is not None]
        explicit = [candidate for candidate in candidates if candidate.number is not None]
        if explicit:
            number = min(candidate.number for candidate in explicit)
            candidates = [candidate for candidate in explicit if candidate.number == number]
        elif candidates:
            group = min(candidate.group for candidate in candidates)
            candidates = [candidate for candidate in candidates if candidate.group == group]
        for candidate in candidates:
            if candidate.role in previews:
                continue
            content = _read_png(archive, candidate)
            with Image.open(io.BytesIO(content)) as image:
                preview = image.convert('RGBA')
                preview.thumbnail((76, 88), Image.Resampling.LANCZOS)
                previews[candidate.role] = preview.copy()
            if len(previews) == 10:
                break
    return tuple(sorted(previews.items()))
