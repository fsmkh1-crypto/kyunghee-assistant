"""Immutable, named ten-role sets alongside the older per-role image store.

A reserved UUID directory is private until its complete manifest is published.
No settings, numbered packs, source images, or older role manifests are changed.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Mapping
import unicodedata
import uuid
import warnings

from PIL import Image

from image_catalog import MAX_IMAGE_BYTES, MAX_IMAGE_PIXELS, SUPPORTED_SUFFIXES


ROLES = ('default', 'cheer', 'rest', 'away', 'warning', 'leave',
         'stats', 'settings', 'alert', 'profile')
NAMED_SET_PREFIX = 'named:'
ID_PATTERN = re.compile(r'named:[0-9a-f]{32}')
MAX_NAME_LENGTH = 80
MAX_SET_BYTES = 256 * 1024 * 1024
MAX_MANIFEST_BYTES = 64 * 1024
SCHEMA_VERSION = 1


def is_named_set_id(value: object) -> bool:
    return isinstance(value, str) and ID_PATTERN.fullmatch(value) is not None


def normalize_name(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError('세트 이름을 입력해 주세요.')
    if any(not ch.isprintable() and not ch.isspace() for ch in value):
        raise ValueError('세트 이름에 보이지 않는 제어 문자는 사용할 수 없습니다.')
    result = unicodedata.normalize('NFC', ' '.join(value.split()))
    if not result or len(result) > MAX_NAME_LENGTH:
        raise ValueError(f'세트 이름은 1~{MAX_NAME_LENGTH}자로 입력해 주세요.')
    return result


def validate_manifest(raw: object, expected_id: str | None = None) -> dict:
    """Validate metadata without touching disk; paths are role basenames only."""
    if not isinstance(raw, dict) or set(raw) != {'schema_version', 'id', 'name', 'images'}:
        raise ValueError('이름 세트의 기록 형식이 올바르지 않습니다.')
    if type(raw['schema_version']) is not int or raw['schema_version'] != SCHEMA_VERSION:
        raise ValueError('지원하지 않는 이름 세트 기록 버전입니다.')
    set_id = raw['id']
    if not is_named_set_id(set_id) or (expected_id is not None and set_id != expected_id):
        raise ValueError('이름 세트 ID가 저장 폴더와 일치하지 않습니다.')
    name = normalize_name(raw['name'])
    if name != raw['name']:
        raise ValueError('이름 세트의 저장된 이름 형식이 올바르지 않습니다.')
    entries = raw['images']
    if not isinstance(entries, dict) or set(entries) != set(ROLES):
        raise ValueError('이름 세트에는 정확히 10개 상황의 이미지가 필요합니다.')
    images, total = {}, 0
    for role in ROLES:
        item = entries[role]
        if not isinstance(item, dict) or set(item) != {'file', 'sha256', 'bytes'}:
            raise ValueError(f'{role} 이미지 기록 형식이 올바르지 않습니다.')
        filename, digest, size = item['file'], item['sha256'], item['bytes']
        if not isinstance(filename, str) or filename not in {role + suffix for suffix in SUPPORTED_SUFFIXES}:
            raise ValueError(f'{role} 이미지 경로가 올바르지 않습니다.')
        if not isinstance(digest, str) or re.fullmatch('[0-9a-f]{64}', digest) is None:
            raise ValueError(f'{role} 이미지 확인 값이 올바르지 않습니다.')
        if type(size) is not int or not 0 < size <= MAX_IMAGE_BYTES:
            raise ValueError(f'{role} 이미지 크기가 올바르지 않습니다.')
        total += size
        images[role] = {'file': filename, 'sha256': digest, 'bytes': size}
    if total > MAX_SET_BYTES:
        raise ValueError('이름 세트의 전체 이미지 크기가 너무 큽니다.')
    return {'schema_version': SCHEMA_VERSION, 'id': set_id, 'name': name, 'images': images}


@dataclass(frozen=True)
class PlannedImage:
    role: str
    source: Path
    resolved_source: Path
    sha256: str
    size: int
    suffix: str


@dataclass(frozen=True)
class NamedImageSetPlan:
    requested_name: str
    name: str
    root: Path
    images: tuple[PlannedImage, ...]

    @property
    def sources(self) -> dict[str, Path]:
        return {image.role: image.source for image in self.images}


@dataclass(frozen=True)
class NamedImageSet:
    id: str
    name: str
    images: dict[str, Path]


def _plain_path(path: Path) -> None:
    for component in (path, *path.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('연결된 폴더나 파일에는 이름 세트를 저장하거나 불러올 수 없습니다.')


def _unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('이름 세트 기록에 중복 항목이 있습니다.')
        result[key] = value
    return result


def _read_manifest(path: Path) -> object:
    _plain_path(path)
    with path.open('rb') as handle:
        content = handle.read(MAX_MANIFEST_BYTES + 1)
    if len(content) > MAX_MANIFEST_BYTES:
        raise ValueError('이름 세트 기록이 너무 큽니다.')
    return json.loads(content, object_pairs_hook=_unique_json)


class NamedImageSetStore:
    def __init__(self, root: Path):
        self.root = Path(root).absolute()
        self.sets_dir = self.root / 'named'
        self.lock_path = self.root / '.named_sets.lock'
        # Content hashes, not timestamps, key this decode cache. Every read
        # still checks all bytes against the immutable manifest fingerprint.
        self._validated_hashes: set[str] = set()

    def _directories(self) -> tuple[Path, ...]:
        _plain_path(self.sets_dir)
        if not self.sets_dir.exists():
            return ()
        if not self.sets_dir.is_dir():
            raise ValueError('이름 세트 저장 경로가 폴더가 아닙니다.')
        return tuple(sorted((p for p in self.sets_dir.iterdir()
                             if re.fullmatch('[0-9a-fA-F]{32}', p.name)), key=lambda p: p.name))

    def _used_names(self) -> set[str]:
        used = set()
        for folder in self._directories():
            _plain_path(folder)
            if not folder.is_dir():
                continue  # A file still reserves its ID when mkdir is attempted.
            manifest = folder / 'manifest.json'
            _plain_path(manifest)
            if not manifest.exists():
                continue  # Incomplete, unpublished directories reserve IDs only.
            try:
                raw = _read_manifest(manifest)
                name = normalize_name(raw['name'])
            except (OSError, ValueError, KeyError, TypeError, UnicodeError, RecursionError) as exc:
                raise ValueError('기존 이름 세트 기록을 읽을 수 없어 새 저장을 중단했습니다. '
                                 '기존 파일은 보존됩니다.') from exc
            # Even unsupported future schemas or damaged images reserve names.
            used.add(name.casefold())
        return used

    @staticmethod
    def _available_name(requested: str, used: set[str]) -> str:
        if requested.casefold() not in used:
            return requested
        for index in range(2, len(used) + 3):
            suffix = f' ({index})'
            candidate = requested[:MAX_NAME_LENGTH - len(suffix)].rstrip() + suffix
            if candidate.casefold() not in used:
                return candidate
        raise ValueError('사용할 수 있는 세트 이름을 찾지 못했습니다.')

    def _read_image(self, path: Path) -> tuple[bytes, str]:
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ValueError(f'지원하지 않는 이미지 형식입니다: {path.name}')
        with path.open('rb') as handle:
            content = handle.read(MAX_IMAGE_BYTES + 1)
        if not 0 < len(content) <= MAX_IMAGE_BYTES:
            raise ValueError(f'이미지 파일 크기를 확인해 주세요: {path.name}')
        digest = hashlib.sha256(content).hexdigest()
        if digest not in self._validated_hashes:
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter('error', Image.DecompressionBombWarning)
                    with Image.open(io.BytesIO(content)) as picture:
                        if picture.format not in {'PNG', 'JPEG', 'WEBP'} or picture.width * picture.height > MAX_IMAGE_PIXELS:
                            raise ValueError('지원하지 않는 이미지')
                        picture.verify()
                    with Image.open(io.BytesIO(content)) as picture:
                        picture.convert('RGBA').load()
            except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
                raise ValueError(f'이미지를 완전히 읽을 수 없습니다: {path.name}') from None
            self._validated_hashes.add(digest)
        return content, digest

    def preview(self, name: str, assignments: Mapping[str, Path]) -> NamedImageSetPlan:
        requested = normalize_name(name)
        if not isinstance(assignments, Mapping) or set(assignments) != set(ROLES):
            raise ValueError('새 전체 세트에는 10개 상황 모두에 이미지를 배정해 주세요.')
        final_name = self._available_name(requested, self._used_names())
        images, total = [], 0
        for role in ROLES:
            source = Path(assignments[role]).expanduser().absolute()
            resolved = source.resolve(strict=True)
            content, digest = self._read_image(source)
            total += len(content)
            if total > MAX_SET_BYTES:
                raise ValueError('세트 전체 이미지 크기는 256 MiB 이하여야 합니다.')
            images.append(PlannedImage(role, source, resolved, digest, len(content), source.suffix.lower()))
        return NamedImageSetPlan(requested, final_name, self.root, tuple(images))

    @contextmanager
    def _write_lock(self):
        _plain_path(self.lock_path)
        self.root.mkdir(parents=True, exist_ok=True)
        _plain_path(self.lock_path)
        with self.lock_path.open('a+b') as handle:
            if os.fstat(handle.fileno()).st_size == 0:
                handle.write(b'\0')
                handle.flush()
            handle.seek(0)
            try:
                if os.name == 'nt':
                    import msvcrt
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('다른 세트 저장이 진행 중입니다. 잠시 후 다시 시도해 주세요.') from exc
            try:
                yield
            finally:
                try:
                    handle.seek(0)
                    if os.name == 'nt':
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError:
                    pass  # Closing the handle also releases its process lock.

    @staticmethod
    def _write_file(path: Path, content: bytes, owned: dict[Path, tuple[int, int]]):
        _plain_path(path)
        with path.open('xb') as handle:
            info = os.fstat(handle.fileno())
            owned[path] = (info.st_dev, info.st_ino)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    @staticmethod
    def _remove_owned(owned: dict[Path, tuple[int, int]], directory: Path,
                      directory_identity: tuple[int, int]):
        for path, identity in reversed(tuple(owned.items())):
            try:
                info = path.lstat()
                if not stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) == identity:
                    path.unlink()
            except OSError:
                pass
        try:
            info = directory.lstat()
            if not stat.S_ISLNK(info.st_mode) and (info.st_dev, info.st_ino) == directory_identity:
                directory.rmdir()  # Never remove files another writer placed here.
        except OSError:
            pass

    def save(self, plan: NamedImageSetPlan) -> NamedImageSet:
        if not isinstance(plan, NamedImageSetPlan) or plan.root != self.root:
            raise ValueError('이 저장 위치에서 미리보기를 다시 확인해 주세요.')
        if (not all(isinstance(item, PlannedImage) for item in plan.images)
                or len(plan.images) != len(ROLES) or {item.role for item in plan.images} != set(ROLES)):
            raise ValueError('저장할 10개 상황 배정을 다시 확인해 주세요.')
        requested = normalize_name(plan.requested_name)
        if requested != plan.requested_name or normalize_name(plan.name) != plan.name:
            raise ValueError('세트 이름을 다시 확인해 주세요.')
        _plain_path(self.sets_dir)
        with self._write_lock():
            if self._available_name(requested, self._used_names()) != plan.name:
                raise ValueError('미리보기 이후 같은 이름의 세트가 생겼습니다. 미리보기를 다시 확인해 주세요.')
            self.sets_dir.mkdir(parents=True, exist_ok=True)
            _plain_path(self.sets_dir)
            occupied = {path.name.casefold() for path in self.sets_dir.iterdir()}
            directory = None
            for _ in range(32):
                identifier = uuid.uuid4().hex
                if re.fullmatch('[0-9a-f]{32}', identifier) is None or identifier in occupied:
                    continue
                candidate = self.sets_dir / identifier
                try:
                    candidate.mkdir(exist_ok=False)
                except FileExistsError:
                    occupied.add(identifier)
                    continue
                directory = candidate
                break
            if directory is None:
                raise ValueError('새 세트 ID를 만들지 못했습니다. 기존 세트는 보존됩니다.')
            directory_stat = directory.lstat()
            directory_identity = (directory_stat.st_dev, directory_stat.st_ino)
            set_id = NAMED_SET_PREFIX + directory.name
            owned: dict[Path, tuple[int, int]] = {}
            try:
                images, entries = {}, {}
                for item in plan.images:
                    if item.suffix not in SUPPORTED_SUFFIXES or item.source.suffix.lower() != item.suffix:
                        raise ValueError('이미지 배정을 다시 확인해 주세요.')
                    if item.source.resolve(strict=True) != item.resolved_source:
                        raise ValueError('미리보기 이후 원본 이미지 위치가 바뀌었습니다. 다시 확인해 주세요.')
                    content, digest = self._read_image(item.source)
                    if digest != item.sha256 or len(content) != item.size:
                        raise ValueError('미리보기 이후 원본 이미지가 바뀌었습니다. 다시 확인해 주세요.')
                    path = directory / (item.role + item.suffix)
                    self._write_file(path, content, owned)
                    images[item.role] = path
                    entries[item.role] = {'file': path.name, 'sha256': digest, 'bytes': len(content)}
                manifest = validate_manifest({'schema_version': SCHEMA_VERSION, 'id': set_id,
                                              'name': plan.name, 'images': entries}, set_id)
                temporary = directory / '.manifest.tmp'
                self._write_file(temporary, json.dumps(manifest, ensure_ascii=False, indent=2).encode('utf-8'), owned)
                _plain_path(directory)
                published = directory / 'manifest.json'
                # A hard link publishes a complete file atomically and refuses
                # every existing destination. rename/replace could overwrite it.
                os.link(temporary, published)
                owned[published] = owned[temporary]
                temporary.unlink()
                return NamedImageSet(set_id, plan.name, images)
            except BaseException:
                self._remove_owned(owned, directory, directory_identity)
                raise

    def create(self, name: str, assignments: Mapping[str, Path]) -> NamedImageSet:
        return self.save(self.preview(name, assignments))

    def get(self, set_id: str) -> NamedImageSet | None:
        if not is_named_set_id(set_id):
            return None
        directory = self.sets_dir / set_id[len(NAMED_SET_PREFIX):]
        try:
            manifest = validate_manifest(_read_manifest(directory / 'manifest.json'), set_id)
            images = {}
            for role, entry in manifest['images'].items():
                path = directory / entry['file']
                _plain_path(path)
                content, digest = self._read_image(path)
                if len(content) != entry['bytes'] or digest != entry['sha256']:
                    return None
                images[role] = path
            return NamedImageSet(set_id, manifest['name'], images)
        except (OSError, ValueError, TypeError, UnicodeError, RecursionError):
            return None

    def list_sets(self) -> tuple[NamedImageSet, ...]:
        sets = (self.get(NAMED_SET_PREFIX + path.name) for path in self._directories())
        return tuple(sorted((item for item in sets if item is not None), key=lambda item: (item.name.casefold(), item.id)))

    def resolve(self, set_id: str, role: str) -> Path | None:
        if role not in ROLES:
            return None
        image_set = self.get(set_id)
        return image_set.images[role] if image_set is not None else None
