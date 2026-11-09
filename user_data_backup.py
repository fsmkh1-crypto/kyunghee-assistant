"""Local, selective profile backup. No network access and no application imports.

Restore is a quiescent transaction: callers must stop all profile writers first,
and exit without saving their old in-memory state after success. Each replacement
is atomic; a failed transaction rolls back every replacement. The private journal
is retained if rollback itself fails, so the originals are never discarded.
"""
from __future__ import annotations

from contextlib import closing
from dataclasses import asdict, dataclass, fields
from datetime import date, datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import sqlite3
import stat
import tempfile
import time
import uuid
import warnings
import zipfile

from app_brand import APP_VERSION


FORMAT = "seunga-user-data"
SCHEMA_VERSION = 1
MAX_FILES = 3000
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000
CATEGORY_LABELS = {
    "timer": "타이머 기록", "settings": "앱·AI 설정", "images": "사용자 이미지·이미지 세트",
    "chat": "저장된 AI 대화·기억·사용량",
}
ROOTS = {
    "timer": ("state.json",),
    "settings": ("settings.json", "ai_settings.json"),
    "images": ("images", "image_sets", "imported_assets", "manual_asset_overrides.json"),
    "chat": ("memory.sqlite3", "ai_usage.sqlite3"),
}
IMAGE_ROOTS = {"images", "image_sets", "imported_assets"}
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
_SECRET = re.compile(
    r"(?i)\b(?:sk-[a-z0-9_-]{8,}|(?:gh[pousr]_|github_pat_)[a-z0-9_]{10,}|"
    r"AKIA[A-Z0-9]{16}|Bearer\s+[a-z0-9._~+/-]{8,})\b"
)
_ASSIGNMENT = re.compile(
    r"(?i)((?:api[_ -]?key|access[_ -]?token|secret|password)\s*[:=]\s*)[^\s,;]+"
)
_PRIVATE_KEY = re.compile(r"-----BEGIN [^-]*PRIVATE KEY-----.*?-----END [^-]*PRIVATE KEY-----", re.S)


class BackupError(ValueError):
    """A safe, user-readable error without file contents or full paths."""


class RestoreRecoveryError(BackupError):
    """Rollback was incomplete: the application must not resume profile writes."""

    def __init__(self, message, recovery_backup):
        super().__init__(message)
        self.recovery_backup = recovery_backup


@dataclass(frozen=True)
class BackupPreview:
    categories: tuple[str, ...]
    file_count: int
    total_bytes: int
    counts: dict[str, int]
    created_at: str = ""
    fingerprint: str = ""


@dataclass(frozen=True)
class RestoreResult:
    recovery_backup: Path
    restored_categories: tuple[str, ...]
    recovery_required: bool = False


def default_data_dir() -> Path:
    # Do not scan or migrate the separate LOCALAPPDATA AI Review profile.
    return Path(os.getenv("APPDATA", Path.home())) / "KyungheeAssistant"


def _selection(categories) -> tuple[str, ...]:
    result = tuple(key for key in CATEGORY_LABELS if key in categories)
    if not result or set(categories) - CATEGORY_LABELS.keys():
        raise BackupError("백업 또는 복원할 항목을 선택해 주세요.")
    return result


def _safe_name(name: str) -> str:
    if not isinstance(name, str) or not name or len(name) > 240 or "\\" in name or ":" in name or "\x00" in name:
        raise BackupError("안전하지 않은 파일 이름이 포함되어 있어요.")
    path = PurePosixPath(name)
    if path.is_absolute() or any(p in {"", ".", ".."} for p in name.split("/")):
        raise BackupError("백업 파일 경로가 올바르지 않아요.")
    # Reject Windows aliases, ADS, and device names even when checking on Linux.
    for part in path.parts:
        if part.rstrip(" .") != part or re.match(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", part):
            raise BackupError("Windows에서 사용할 수 없는 파일 이름이 있어요.")
        if any(ord(c) < 32 or c in '<>"|?*' for c in part):
            raise BackupError("안전하지 않은 파일 이름이 포함되어 있어요.")
    return name


def _plain_path(path: Path) -> None:
    """Reject links/junctions at every existing component, including ancestors."""
    for item in (path, *path.parents):
        try:
            info = item.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise BackupError("심볼릭 링크나 연결 폴더는 백업·복원할 수 없어요.")


def _category(name: str) -> str:
    _safe_name(name)
    first = name.split("/", 1)[0]
    for category, roots in ROOTS.items():
        if first in roots:
            if "/" not in name and first not in IMAGE_ROOTS:
                return category
            if first in IMAGE_ROOTS and "/" in name:
                if Path(name).suffix.lower() in IMAGE_SUFFIXES:
                    return category
                if name == "image_sets/image_sets.json":
                    return category
    raise BackupError("이 사용자 데이터 백업에서 지원하지 않는 파일이 있어요.")


def _redact(text: str) -> str:
    text = _PRIVATE_KEY.sub("[보안 정보 제외]", text)
    return _ASSIGNMENT.sub(r"\1[보안 정보 제외]", _SECRET.sub("[보안 정보 제외]", text))


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")


def _read_limited(path: Path, limit=MAX_FILE_BYTES) -> bytes:
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise BackupError("파일이 허용 크기를 초과했어요.")
    return data


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            result.update(chunk)
    return result.hexdigest()


def _export_destination(data_dir: Path, output: Path) -> None:
    _plain_path(output)
    try:
        # absolute() retains '..'; normalize after rejecting links/junctions.
        relative = output.resolve(strict=False).relative_to(data_dir.resolve(strict=False))
    except ValueError:
        return
    if len(relative.parts) < 2 or relative.parts[0] != "backups":
        raise BackupError("사용자 데이터 폴더에는 backups 하위 폴더에만 내보낼 수 있어요. 다른 저장 위치를 선택해 주세요.")


def _json_read(data: bytes) -> dict:
    if len(data) > MAX_JSON_BYTES:
        raise BackupError("설정 파일이 허용 크기를 초과했어요.")
    try:
        raw = json.loads(data)
    except (UnicodeError, ValueError, RecursionError):
        raise BackupError("JSON 설정 파일이 손상되었어요.") from None
    if not isinstance(raw, dict):
        raise BackupError("설정 파일의 형식이 올바르지 않아요.")
    return raw


def _relative_image(value: object, data_dir: Path | None) -> str:
    if not isinstance(value, str) or not value:
        return ""
    if value.startswith("$DATA/"):
        relative = value[6:]
    elif data_dir is not None:
        try:
            if not Path(value).is_absolute() and "/" not in value and "\\" not in value:
                # Earlier single-image imports stored just destination.name.
                _safe_name(value)
                relative = "images/" + value
            else:
                relative = Path(value).resolve(strict=False).relative_to(data_dir.resolve(strict=False)).as_posix()
        except ValueError:
            return ""  # External source paths are not portable or app-owned.
    else:
        return ""
    try:
        return "$DATA/" + relative if _category(relative) == "images" else ""
    except BackupError:
        return ""


def _clean_json(name: str, data: bytes, data_dir: Path | None = None) -> bytes:
    raw = _json_read(data)
    if name == "settings.json":
        from settings import UserSettings, settings_from_dict
        known = {f.name for f in fields(UserSettings)}
        clean = asdict(settings_from_dict({k: v for k, v in raw.items() if k in known}))
        for key in clean:
            if key.startswith("image_") and not key.endswith("_mode"):
                clean[key] = _relative_image(clean[key], data_dir)
            elif isinstance(clean[key], str):
                clean[key] = _redact(clean[key])
        return _json_bytes(clean)
    if name == "ai_settings.json":
        from assistant_ai.config import AISettings
        try:
            values = {f.name: raw[f.name] for f in fields(AISettings) if f.name in raw}
            if isinstance(values.get("proactive_events"), list):
                values["proactive_events"] = tuple(values["proactive_events"])
            values.setdefault("conversation_storage_enabled", raw.get("memory_enabled", False))
            clean = AISettings(**values)
            clean.validate()
        except (ValueError, TypeError):
            raise BackupError("AI 설정 파일의 값이 올바르지 않아요.") from None
        return _json_bytes({k: _redact(v) if isinstance(v, str) else v for k, v in asdict(clean).items()})
    if name == "state.json":
        from state import DailyStats, SessionState, SCHEMA_VERSION as STATE_SCHEMA
        def record(value, cls):
            if not isinstance(value, dict):
                raise BackupError("타이머 기록 형식이 올바르지 않아요.")
            result = {}
            for field in fields(cls):
                default = getattr(cls(), field.name)
                v = value.get(field.name, default)
                if field.name == "day":
                    if not isinstance(v, str) or (v and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", v)):
                        raise BackupError("타이머 날짜가 올바르지 않아요.")
                    try:
                        if v:
                            date.fromisoformat(v)
                    except ValueError:
                        raise BackupError("타이머 날짜가 올바르지 않아요.") from None
                elif type(default) is bool:
                    if type(v) is not bool:
                        raise BackupError("타이머 상태 값이 올바르지 않아요.")
                elif v is None and default is None:
                    pass
                elif type(v) not in (int, float) or not 0 <= v <= 1e15 or not math.isfinite(v):
                    raise BackupError("타이머 기록 값이 올바르지 않아요.")
                elif type(default) is int and type(v) is not int:
                    raise BackupError("타이머 횟수 값이 올바르지 않아요.")
                result[field.name] = v
            return result
        history = raw.get("history", [])
        if not isinstance(history, list) or len(history) > 1000:
            raise BackupError("타이머 과거 기록 형식이 올바르지 않아요.")
        return _json_bytes({"schema_version": STATE_SCHEMA, "daily": record(raw.get("daily", {}), DailyStats),
                            "session": record(raw.get("session", {}), SessionState),
                            "history": [record(v, DailyStats) for v in history]})
    if name == "image_sets/image_sets.json":
        from image_sets import ImageSetConfig
        roles = raw.get("roles", {})
        if not isinstance(roles, dict) or len(roles) > 100:
            raise BackupError("이미지 세트 목록이 올바르지 않아요.")
        result = {}
        for role, entry in roles.items():
            if not re.fullmatch(r"[a-z_]{1,40}", role):
                raise BackupError("이미지 역할 이름이 올바르지 않아요.")
            config = ImageSetConfig.from_dict(role, entry)
            for relative in config.images:
                if _category("image_sets/" + relative) != "images" or not relative.startswith("roles/"):
                    raise BackupError("이미지 세트 경로가 올바르지 않아요.")
            result[role] = config.to_dict()
        return _json_bytes({"schema_version": 1, "roles": result})
    if name == "manual_asset_overrides.json":
        clean = {}
        def valid_reference(ref):
            scheme, sep, relative = ref.partition(":")
            if sep and scheme in {"builtin", "user", "userset", "imported"}:
                _safe_name(relative)
                return Path(relative).suffix.lower() in IMAGE_SUFFIXES
            return False
        for role, ref in raw.items():
            if role == "__base_set__":
                if isinstance(ref, str) and re.fullmatch(r"(?:random|canonical|[0-9]{2}|pack:[0-9]{2})", ref):
                    clean[role] = ref
                continue
            if not re.fullmatch(r"[a-z_]{1,40}", role) or not isinstance(ref, str):
                continue
            if ref == "__follow_selected_set__":
                clean[role] = ref
            elif ref.startswith("userset-group:"):
                try:
                    members = json.loads(ref[len("userset-group:"):])
                except (ValueError, RecursionError):
                    raise BackupError("수동 이미지 그룹 목록이 올바르지 않아요.") from None
                if not isinstance(members, list) or len(members) > MAX_FILES or not all(isinstance(member, str) and valid_reference(member) for member in members):
                    raise BackupError("수동 이미지 그룹 경로가 올바르지 않아요.")
                clean[role] = "userset-group:" + json.dumps(members, ensure_ascii=False)
            elif valid_reference(ref):
                clean[role] = ref
        return _json_bytes(clean)
    raise BackupError("알 수 없는 설정 파일이에요.")


_DB_SCHEMAS = {
    "memory.sqlite3": {
        "storage_state": ("id, enabled, generation, history_enabled", "id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL, generation INTEGER NOT NULL, history_enabled INTEGER NOT NULL DEFAULT 0"),
        "conversation_turns": ("id, user_text, assistant_text, created_at, generation, status", "id INTEGER PRIMARY KEY AUTOINCREMENT, user_text TEXT NOT NULL, assistant_text TEXT, created_at TEXT NOT NULL, generation INTEGER NOT NULL, status TEXT NOT NULL DEFAULT 'pending'"),
        "memories": ("id, text, normalized_text, created_at, pinned", "id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL, normalized_text TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0"),
    },
    "ai_usage.sqlite3": {
        "calls": ("id, day, created_at, model, status, input_tokens, output_tokens, total_tokens, cost_nanos, purpose", "id INTEGER PRIMARY KEY, day TEXT NOT NULL, created_at TEXT NOT NULL, model TEXT NOT NULL, status TEXT NOT NULL, input_tokens INTEGER NOT NULL, output_tokens INTEGER NOT NULL, total_tokens INTEGER NOT NULL, cost_nanos INTEGER, purpose TEXT NOT NULL DEFAULT 'legacy'"),
    },
}


def _safe_database(source: Path, target: Path, name: str, *, live: bool) -> None:
    """Snapshot a live WAL DB, then rebuild known tables to omit freed/private pages."""
    deadline = time.monotonic() + 15
    page_size = 4096
    def progress(status, remaining, total):
        if total * page_size > MAX_FILE_BYTES:
            raise BackupError("데이터베이스가 허용 크기를 초과했어요.")
        if time.monotonic() > deadline:
            raise BackupError("데이터베이스 사용 중이에요. 잠시 후 다시 시도해 주세요.")
    schema = _DB_SCHEMAS[name]
    try:
        with tempfile.TemporaryDirectory(dir=target.parent) as tmp:
            snapshot = Path(tmp) / "snapshot.sqlite3"
            uri = source.absolute().as_uri() + ("?mode=ro" if live else "?mode=ro&immutable=1")
            with closing(sqlite3.connect(uri, uri=True, timeout=2)) as original:
                original.execute("PRAGMA trusted_schema=OFF")
                page_size = original.execute("PRAGMA page_size").fetchone()[0]
                if original.execute("PRAGMA page_count").fetchone()[0] * page_size > MAX_FILE_BYTES:
                    raise BackupError("데이터베이스가 허용 크기를 초과했어요.")
                with closing(sqlite3.connect(snapshot)) as copied:
                    original.backup(copied, pages=128, progress=progress, sleep=0.01)
            if snapshot.stat().st_size > MAX_FILE_BYTES:
                raise BackupError("데이터베이스가 허용 크기를 초과했어요.")
            with closing(sqlite3.connect(snapshot)) as src, closing(sqlite3.connect(target)) as dst:
                src.execute("PRAGMA trusted_schema=OFF")
                src.execute("PRAGMA query_only=ON")
                src.set_progress_handler(lambda: int(time.monotonic() > deadline), 1000)
                if src.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BackupError("데이터베이스 무결성 검사에 실패했어요.")
                objects = src.execute("SELECT type,name FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                if any(kind not in {"table", "index"} or (kind == "table" and obj not in schema) for kind, obj in objects):
                    raise BackupError("데이터베이스에 지원하지 않는 구조가 있어요.")
                if {obj for kind, obj in objects if kind == "table"} != set(schema):
                    raise BackupError("데이터베이스 필수 테이블이 없어요.")
                with dst:
                    for table, (columns, definition) in schema.items():
                        expected = columns.split(", ")
                        actual = [v[1] for v in src.execute(f'PRAGMA table_info("{table}")')]
                        query_columns = columns
                        legacy_defaults = {"storage_state": "enabled", "memories": "0", "calls": "'legacy'",
                                           "conversation_turns": "CASE WHEN assistant_text IS NULL THEN 'interrupted' ELSE 'completed' END"}
                        if table in legacy_defaults and actual == expected[:-1]:
                            query_columns = ", ".join(actual) + ", " + legacy_defaults[table]
                        elif actual != expected:
                            raise BackupError("데이터베이스 버전 또는 열 구성이 맞지 않아요.")
                        dst.execute(f'CREATE TABLE "{table}" ({definition})')
                        for row in src.execute(f'SELECT {query_columns} FROM "{table}"'):
                            for column, value in zip(expected, row):
                                if value is None and column in {"assistant_text", "cost_nanos"}:
                                    continue
                                numeric = column in {"id", "enabled", "generation", "history_enabled", "pinned", "input_tokens", "output_tokens", "total_tokens", "cost_nanos"}
                                if (numeric and (type(value) is not int or value < 0)) or (not numeric and (not isinstance(value, str) or len(value) > MAX_JSON_BYTES)):
                                    raise BackupError("데이터베이스 내용의 형식이 올바르지 않아요.")
                                if column in {"enabled", "history_enabled", "pinned"} and value not in (0, 1):
                                    raise BackupError("데이터베이스 저장 상태가 올바르지 않아요.")
                                if table == "conversation_turns" and column == "status" and value not in {"pending", "completed", "failed", "cancelled", "interrupted"}:
                                    raise BackupError("대화 상태가 올바르지 않아요.")
                            safe = tuple(_redact(v) if isinstance(v, str) else v for v in row)
                            # Two memories can become identical after key masking.
                            # Retain one sanitized value rather than fail or leak it.
                            verb = "INSERT OR IGNORE" if table == "memories" else "INSERT"
                            dst.execute(f'{verb} INTO "{table}" VALUES ({",".join("?" for _ in safe)})', safe)
                    if name == "memory.sqlite3":
                        rows = dst.execute("SELECT id, enabled, generation FROM storage_state").fetchall()
                        if len(rows) != 1 or rows[0][0] != 1 or rows[0][1] not in (0, 1):
                            raise BackupError("대화 저장 상태가 올바르지 않아요.")
                    else:
                        dst.execute("CREATE INDEX calls_by_day ON calls(day)")
                if dst.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
                    raise BackupError("데이터베이스 검증에 실패했어요.")
    except sqlite3.Error:
        raise BackupError("데이터베이스가 손상되었거나 현재 읽을 수 없어요.") from None


def _check_image(path: Path) -> None:
    from PIL import Image
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as picture:
                if picture.width * picture.height > MAX_IMAGE_PIXELS or picture.format not in {"PNG", "JPEG", "WEBP"}:
                    raise BackupError("이미지 크기 또는 형식이 허용 범위를 벗어났어요.")
                picture.verify()
            with Image.open(path) as picture:
                picture.load()
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise BackupError("읽을 수 없거나 너무 큰 이미지가 있어요.") from None


def _source_files(data_dir: Path, categories: tuple[str, ...]):
    _plain_path(data_dir)
    for category in categories:
        for root_name in ROOTS[category]:
            root = data_dir / root_name
            _plain_path(root)
            if not root.exists():
                continue
            candidates = root.rglob("*") if root_name in IMAGE_ROOTS else [root]
            for index, path in enumerate(candidates):
                if index > MAX_FILES * 2:
                    raise BackupError("이미지 폴더의 항목 수가 안전 한도를 초과했어요.")
                _plain_path(path)
                if path.is_dir():
                    continue
                name = path.relative_to(data_dir).as_posix()
                try:
                    _category(name)
                except BackupError:
                    # Never copy keys, logs, unknown JSON, adoption markers, or sidecars.
                    continue
                if not stat.S_ISREG(path.stat().st_mode):
                    raise BackupError("일반 파일이 아닌 항목은 백업할 수 없어요.")
                yield category, name, path


def preview_source(data_dir: Path, categories) -> BackupPreview:
    selected = _selection(categories)
    counts = {c: 0 for c in selected}
    total = 0
    for category, _, path in _source_files(Path(data_dir), selected):
        size = path.stat().st_size
        counts[category] += 1
        total += size
        if size > MAX_FILE_BYTES or sum(counts.values()) > MAX_FILES or total > MAX_TOTAL_BYTES:
            raise BackupError("선택한 데이터가 백업 크기 한도를 초과했어요.")
    return BackupPreview(selected, sum(counts.values()), total, counts)


def create_backup(data_dir: Path, output: Path, categories, *, app_version: str = APP_VERSION) -> BackupPreview:
    data_dir, output = Path(data_dir).absolute(), Path(output).absolute()
    selected = _selection(categories)
    preview_source(data_dir, selected)
    _export_destination(data_dir, output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".seunga-backup-", dir=output.parent) as tmp:
        staging = Path(tmp)
        entries = []
        total = 0
        for category, name, source in _source_files(data_dir, selected):
            target = staging / "data" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            if name in _DB_SCHEMAS:
                _safe_database(source, target, name, live=True)
            elif source.suffix.lower() == ".json":
                target.write_bytes(_clean_json(name, _read_limited(source, MAX_JSON_BYTES), data_dir))
            else:
                _check_image(source)
                target.write_bytes(_read_limited(source))
            size = target.stat().st_size
            total += size
            if size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or len(entries) >= MAX_FILES:
                raise BackupError("백업 크기 한도를 초과했어요.")
            entries.append({"name": name, "category": category, "size": size,
                            "sha256": _digest(target)})
        manifest = {"format": FORMAT, "schema_version": SCHEMA_VERSION,
                    "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "app_version": _version(app_version), "categories": list(selected), "files": entries}
        archive = staging / "backup.zip"
        # Stored entries have predictable limits and cannot become compression bombs.
        # Windows requires a writable descriptor for fsync. Keep ownership of
        # the writer until ZIP.close() has written the central directory, then
        # flush and sync all bytes before closing and atomically publishing it.
        with archive.open("w+b") as handle:
            with zipfile.ZipFile(handle, "w", compression=zipfile.ZIP_STORED) as bundle:
                bundle.writestr("manifest.json", _json_bytes(manifest))
                for entry in entries:
                    bundle.write(staging / "data" / entry["name"], "data/" + entry["name"])
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(archive, output)
    return inspect_backup(output)


def _read_bundle(archive: Path, staging: Path | None = None) -> tuple[dict, BackupPreview]:
    _plain_path(archive)
    if archive.stat().st_size > MAX_TOTAL_BYTES + 8 * 1024 * 1024:
        raise BackupError("백업 파일 크기 한도를 초과했어요.")
    try:
        with zipfile.ZipFile(archive) as bundle:
            infos = bundle.infolist()
            if len(infos) > MAX_FILES + 1:
                raise BackupError("백업 파일 수 한도를 초과했어요.")
            names = set()
            total = 0
            for info in infos:
                _safe_name(info.filename)
                mode = info.external_attr >> 16
                if info.is_dir() or stat.S_ISLNK(mode) or stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    raise BackupError("백업에 링크 또는 특수 파일이 포함되어 있어요.")
                folded = info.filename.casefold()
                if folded in names or info.flag_bits & 1:
                    raise BackupError("중복 파일 또는 암호화된 항목은 지원하지 않아요.")
                names.add(folded)
                total += info.file_size
                if info.file_size > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES or info.file_size > max(info.compress_size * 200, 1024 * 1024):
                    raise BackupError("압축 파일의 크기 또는 압축률이 안전 한도를 초과했어요.")
            if "manifest.json" not in bundle.namelist():
                raise BackupError("사용자 데이터 백업이 아니에요. 이미지 ZIP 팩은 이미지 설정에서 가져와 주세요.")
            manifest = _json_read(bundle.read("manifest.json"))
            if manifest.get("format") != FORMAT or manifest.get("schema_version") != SCHEMA_VERSION:
                raise BackupError("지원하는 승아 사용자 데이터 백업 형식이 아니에요.")
            categories = manifest.get("categories")
            if not isinstance(categories, list) or any(not isinstance(c, str) for c in categories) or len(set(categories)) != len(categories):
                raise BackupError("백업 항목 목록이 올바르지 않아요.")
            selected = _selection(categories)
            entries = manifest.get("files")
            if not isinstance(entries, list) or len(entries) > MAX_FILES:
                raise BackupError("백업 파일 목록이 올바르지 않아요.")
            counts, listed, total = {c: 0 for c in selected}, {"manifest.json"}, 0
            for entry in entries:
                if not isinstance(entry, dict) or not isinstance(entry.get("name"), str):
                    raise BackupError("백업 파일 설명이 올바르지 않아요.")
                name = entry["name"]
                category = _category(name)
                member = "data/" + name
                if category not in selected or entry.get("category") != category or member in listed:
                    raise BackupError("백업 파일 분류가 올바르지 않아요.")
                listed.add(member)
                data = bundle.read(member)
                if type(entry.get("size")) is not int or len(data) != entry["size"] or hashlib.sha256(data).hexdigest() != entry.get("sha256"):
                    raise BackupError("백업 파일이 변경되었거나 손상되었어요.")
                counts[category] += 1
                total += len(data)
                if staging is not None:
                    target = staging / name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if name.endswith(".json"):
                        target.write_bytes(_clean_json(name, data))
                    elif name in _DB_SCHEMAS:
                        original = staging / (".source-" + uuid.uuid4().hex)
                        original.write_bytes(data)
                        try:
                            _safe_database(original, target, name, live=False)
                        finally:
                            original.unlink(missing_ok=True)
                    else:
                        target.write_bytes(data)
                        _check_image(target)
            if listed != set(bundle.namelist()):
                raise BackupError("목록에 없는 파일이 백업에 포함되어 있어요.")
            created_at = manifest.get("created_at", "")
            if not isinstance(created_at, str) or not re.fullmatch(r"[0-9T:+.Z-]{1,40}", created_at):
                raise BackupError("백업 생성 날짜가 올바르지 않아요.")
            return manifest, BackupPreview(selected, len(entries), total, counts, created_at,
                                          _digest(archive))
    except (zipfile.BadZipFile, KeyError, RuntimeError, NotImplementedError):
        raise BackupError("ZIP 백업 파일이 손상되었거나 지원하지 않는 형식이에요.") from None


def inspect_backup(archive: Path) -> BackupPreview:
    # Preview validates payloads too; the selected archive is never trusted implicitly.
    with tempfile.TemporaryDirectory(prefix="seunga-inspect-") as tmp:
        return _read_bundle(Path(archive), Path(tmp))[1]


def unfinished_restore_journals(data_dir: Path) -> tuple[Path, ...]:
    """Read-only startup guard; incomplete transactions require manual recovery.

    A committed journal is only cleanup debris. A missing, linked or non-file
    commit marker never proves completion. Do not read profile state or start
    writers when this returns a nonempty tuple.
    """
    data_dir = Path(data_dir)
    _plain_path(data_dir)
    pending = []
    for journal in sorted(data_dir.glob(".restore-journal-*")):
        try:
            _plain_path(journal)
            _plain_path(journal / "committed")
            complete = journal.is_dir() and (journal / "committed").is_file()
        except BackupError:
            complete = False
        if not complete:
            pending.append(journal)
    return tuple(pending)


def _destination_key_persistence(data_dir: Path) -> str:
    """A restore never authorizes deleting or persisting a destination key.

    Preserve an existing protected blob even if settings are stale/unreadable;
    otherwise retain the local policy. Only absence of both implies session mode.
    Never open the blob or include it in the backup/recovery archive.
    """
    try:
        (data_dir / "openai_key.dpapi").lstat()
    except FileNotFoundError:
        pass
    except OSError:
        return "windows"  # An unreadable existing key must not be deleted later.
    else:
        return "windows"
    try:
        path = data_dir / "ai_settings.json"
        _plain_path(path)
        policy = _json_read(_read_limited(path, MAX_JSON_BYTES)).get("key_persistence")
        if policy in {"session", "windows"}:
            return policy
    except (OSError, BackupError, TypeError):
        pass
    return "session"


def restore_backup(archive: Path, data_dir: Path, categories, *, app_is_quiescent: bool = False,
                   expected_fingerprint: str = "", app_version: str = APP_VERSION) -> RestoreResult:
    if app_is_quiescent is not True:
        raise BackupError("복원 전에 진행 중인 작업을 마치고 데이터 저장을 중지해야 해요.")
    selected = _selection(categories)
    archive, data_dir = Path(archive).absolute(), Path(data_dir).absolute()
    _plain_path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    if unfinished_restore_journals(data_dir):
        raise BackupError("이전 복원의 복구 폴더가 남아 있어요. 데이터를 보존한 뒤 복구 상태를 확인해 주세요.")
    preview = inspect_backup(archive)
    if set(selected) - set(preview.categories):
        raise BackupError("백업에 없는 항목은 복원할 수 없어요.")
    if expected_fingerprint and expected_fingerprint != preview.fingerprint:
        raise BackupError("미리 보기 이후 백업 파일이 바뀌었어요. 다시 선택해 주세요.")
    key_persistence = _destination_key_persistence(data_dir) if "settings" in selected else None
    recovery = data_dir / "backups" / ("before-restore-" + datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8] + ".seunga-backup.zip")
    create_backup(data_dir, recovery, selected, app_version=app_version)
    journal = data_dir / (".restore-journal-" + uuid.uuid4().hex)
    journal.mkdir(mode=0o700)
    staging, originals = journal / "staged", journal / "originals"
    staging.mkdir()
    originals.mkdir()
    applied = []
    rollback_failed = False
    try:
        # Validate again after the current-data backup, before the first replacement.
        _, final_preview = _read_bundle(archive, staging)
        if preview.fingerprint != final_preview.fingerprint:
            raise BackupError("백업 파일이 복원 도중 변경되었어요.")
        settings_path = staging / "settings.json"
        if "settings" in selected and settings_path.exists():
            raw = _json_read(_read_limited(settings_path, MAX_JSON_BYTES))
            for key, value in raw.items():
                if key.startswith("image_") and isinstance(value, str) and value.startswith("$DATA/"):
                    raw[key] = str(data_dir / value[6:])
            settings_path.write_bytes(_json_bytes(raw))
        if "settings" in selected:
            from assistant_ai.config import AISettings
            ai_path = staging / "ai_settings.json"
            ai_settings = (_json_read(_read_limited(ai_path, MAX_JSON_BYTES))
                           if ai_path.exists() else asdict(AISettings()))
            # Copying a source session policy onto a protected-key destination
            # would delete its blob when AssistantService next starts. Likewise,
            # a source protected policy must not opt the destination into storage.
            ai_settings["key_persistence"] = key_persistence
            ai_path.write_bytes(_clean_json("ai_settings.json", _json_bytes(ai_settings)))
        targets = [name for c in selected for name in ROOTS[c]]
        if "chat" in selected:
            targets += [db + suffix for db in _DB_SCHEMAS for suffix in ("-wal", "-shm", "-journal")]
        for name in targets:
            target = data_dir / name
            _plain_path(target)
            if target.is_dir():
                for child in target.rglob("*"):
                    _plain_path(child)
        (journal / "transaction.json").write_bytes(_json_bytes({"targets": targets, "recovery": recovery.name}))
        for name in targets:
            target, original, replacement = data_dir / name, originals / name, staging / name
            existed = target.exists()
            applied.append((name, existed, False))
            if existed:
                os.replace(target, original)
                applied[-1] = (name, existed, True)
            if replacement.exists():
                os.replace(replacement, target)
        # Commit before removing originals. A cleanup failure must never cause a
        # rollback after some originals have already been removed.
        (journal / "committed").touch()
        try:
            shutil.rmtree(journal)
        except OSError:
            pass
        return RestoreResult(recovery, selected)
    except Exception as error:
        for name, existed, moved in reversed(applied):
            try:
                target, original = data_dir / name, originals / name
                if existed and not moved:
                    continue
                if target.is_dir():
                    shutil.rmtree(target)
                else:
                    target.unlink(missing_ok=True)
                if moved:
                    os.replace(original, target)
            except OSError:
                rollback_failed = True
        if rollback_failed:
            raise RestoreRecoveryError("복원과 자동 되돌리기에 실패했어요. 앱을 종료하고 사용자 데이터의 .restore-journal- 폴더와 backups 복구 백업을 보존해 주세요.", recovery) from error
        if isinstance(error, BackupError):
            raise
        raise BackupError("복원에 실패하여 변경 사항을 모두 되돌렸어요. 현재 데이터 복구 백업은 backups 폴더에 있어요.") from error
    finally:
        if not rollback_failed and journal.exists():
            try:
                shutil.rmtree(journal)
            except OSError:
                pass


def _version(value: str) -> str:
    return value if isinstance(value, str) and re.fullmatch(r"[0-9][0-9A-Za-z.+_-]{0,39}", value) else "unknown"


def _recent_error_categories(data_dir: Path) -> set[str]:
    """Infer fixed categories from at most the final 256 KiB; never return text."""
    path = data_dir / "kyunghee.log"
    patterns = {
        "network": r"\b(network|connection|connectivity)\b",
        "timeout": r"\b(timeout|timed out)\b",
        "authentication": r"\b(authentication|unauthorized|401)\b",
        "rate_limit": r"\b(rate.limit|429)\b",
        "storage": r"\b(storage|sqlite|database|disk|save failed)\b",
        "image": r"\b(image|asset|avatar|decode)\b",
        "ui": r"\b(tkinter|tclerror|widget|geometry)\b",
    }
    try:
        _plain_path(path)
        if not path.is_file():
            return set()
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            handle.seek(max(0, size - 256 * 1024))
            content = handle.read(256 * 1024).decode("utf-8", errors="replace")
    except (OSError, BackupError):
        return set()
    categories = set()
    for line in content.splitlines():
        # Only structured logger level tokens; do not export even exception names.
        if not re.search(r"\b(?:ERROR|WARNING|CRITICAL)\b", line):
            continue
        matched = {name for name, expression in patterns.items() if re.search(expression, line, re.I)}
        categories.update(matched or {"unknown"})
    return categories


def diagnostic_report(data_dir: Path, *, app_version: str = APP_VERSION, error_categories=()) -> dict:
    """Fixed fields only: no log text, DB content, paths, names, locations or keys."""
    config = {}
    for filename, keys in {
        "settings.json": {"schema_version", "always_on_top", "break_reminders", "workday_reminders", "break_interval_minutes", "snooze_minutes", "widget_scale", "show_time", "show_status", "show_message"},
        "ai_settings.json": {"enabled", "proactive_enabled", "memory_enabled", "conversation_storage_enabled", "daily_request_limit", "daily_token_limit", "daily_budget_usd"},
    }.items():
        try:
            path = Path(data_dir) / filename
            _plain_path(path)
            raw = _json_read(_read_limited(path, MAX_JSON_BYTES))
            config[filename] = {k: v for k, v in raw.items() if k in keys and (type(v) is bool or v is None or (type(v) in (int, float) and 0 <= v <= 10_000_000 and math.isfinite(v)))}
        except (OSError, BackupError):
            config[filename] = {"read_status": "unavailable"}
    allowed_errors = {"network", "timeout", "authentication", "rate_limit", "storage", "image", "ui", "unknown"}
    return {"format": "seunga-diagnostics", "schema_version": 1, "app_version": _version(app_version),
            "platform": {"system": platform.system() if platform.system() in {"Windows", "Linux", "Darwin"} else "other", "python": platform.python_version()},
            "safe_configuration": config,
            "error_categories": sorted((set(error_categories) & allowed_errors) | _recent_error_categories(Path(data_dir))),
            "excluded": ["API keys and credentials", "conversation and memory content", "timer records", "images", "raw logs", "absolute paths and usernames", "weather location", "custom dialogue"]}


def export_diagnostics(data_dir: Path, output: Path, **kwargs) -> None:
    output = Path(output)
    _export_destination(Path(data_dir), output)
    output.parent.mkdir(parents=True, exist_ok=True)
    report = _json_bytes(diagnostic_report(data_dir, **kwargs))
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=".diagnostics-", delete=False) as handle:
        tmp = Path(handle.name)
        handle.write(report)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        os.replace(tmp, output)
    finally:
        tmp.unlink(missing_ok=True)
