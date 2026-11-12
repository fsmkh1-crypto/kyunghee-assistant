"""One decoded-image catalog used by settings, dice, imports and assistant tools."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
import hashlib
import json
import warnings
from PIL import Image

SUPPORTED_SUFFIXES = {'.png', '.jpg', '.jpeg', '.webp'}
MAX_IMAGE_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 24_000_000


@lru_cache(maxsize=1024)
def _decoded_image(path: str, mtime: int, size: int) -> bool:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(path) as image:
                if image.format not in {'PNG', 'JPEG', 'WEBP'} or image.width * image.height > MAX_IMAGE_PIXELS:
                    return False
                image.verify()
            with Image.open(path) as image:
                image.convert('RGBA').load()
        return True
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        return False


def valid_image(path: Path) -> bool:
    path = Path(path)
    try:
        stat = path.stat()
        return (path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
                and 0 < stat.st_size <= MAX_IMAGE_BYTES
                and _decoded_image(str(path.resolve()), stat.st_mtime_ns, stat.st_size))
    except (OSError, ValueError):
        return False


def require_image(path: Path) -> Path:
    path = Path(path)
    if not valid_image(path):
        raise ValueError(f'이미지를 완전히 읽을 수 없습니다: {path.name}')
    return path


@dataclass(frozen=True)
class CatalogImage:
    ref: str
    role: str
    label: str
    origin: str
    path: Path

    def public(self) -> dict:
        stat = self.path.stat()
        return {'ref': self.ref, 'role': self.role, 'label': self.label, 'origin': self.origin,
                'version': f'{stat.st_mtime_ns}:{stat.st_size}'}


class ImageCatalog:
    def __init__(self, roots: dict[str, Path], labels: dict[str, str]):
        self.roots = {prefix: Path(root).resolve() for prefix, root in roots.items()}
        self.labels = labels

    def encode(self, path: Path) -> str:
        path = require_image(path).resolve()
        for prefix, root in self.roots.items():
            try:
                return prefix + ':' + path.relative_to(root).as_posix()
            except ValueError:
                continue
        raise ValueError('먼저 이미지를 사용자 보관함으로 가져와 주세요.')

    def decode(self, ref: str, *, legacy_absolute: bool = False) -> Path | None:
        prefix, separator, relative = str(ref or '').partition(':')
        if not separator:
            return None
        if prefix == 'absolute' and legacy_absolute:
            path = Path(relative).expanduser()
            return path if valid_image(path) else None
        root = self.roots.get(prefix)
        if root is None or not relative:
            return None
        try:
            path = (root / relative).resolve()
            path.relative_to(root)
            return path if valid_image(path) else None
        except (OSError, ValueError):
            return None

    def entries(self) -> list[CatalogImage]:
        entries = []
        seen = set()
        for origin, root in self.roots.items():
            if not root.is_dir():
                continue
            if origin in {'builtin', 'imported'}:
                paths = (path for role in self.labels for path in (root / role).glob('*'))
            elif origin == 'userset':
                paths = (root / 'roles').glob('*/*')
            else:
                paths = root.glob('*')
            for path in sorted(paths, key=lambda p: str(p).lower()):
                if not valid_image(path):
                    continue
                resolved = path.resolve()
                if resolved in seen:
                    continue
                try:
                    ref = self.encode(path)
                except ValueError:
                    continue
                seen.add(resolved)
                role = path.parent.name if path.parent.name in self.labels else path.stem.split('_', 1)[0]
                role = role if role in self.labels else 'other'
                entries.append(CatalogImage(ref, role, path.name, origin, path))
        return entries


def catalog_revision(catalog: dict) -> str:
    # Current role/display are live read-only context, not catalog identity.
    # A timer transition must not expire a proposal for an explicitly named role.
    inventory = {key: catalog.get(key) for key in ('roles', 'sets', 'images')}
    return hashlib.sha256(json.dumps(inventory, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
