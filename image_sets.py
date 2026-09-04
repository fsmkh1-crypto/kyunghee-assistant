from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import random
import shutil
import uuid
from typing import Iterable, Sequence


SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}
VALID_FIT_MODES = {"fit", "crop"}
VALID_ALIGNMENTS = {
    "center", "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
}


def normalize_fit_mode(value: object) -> str:
    value = str(value)
    return value if value in VALID_FIT_MODES else "fit"


def normalize_alignment(value: object) -> str:
    value = str(value)
    return value if value in VALID_ALIGNMENTS else "center"


def is_supported_image(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES


@dataclass(frozen=True)
class ImageSetConfig:
    role: str
    images: tuple[str, ...] = ()
    fit_mode: str = "fit"
    alignment: str = "center"

    @classmethod
    def from_dict(cls, role: str, raw: object) -> "ImageSetConfig":
        if not isinstance(raw, dict):
            return cls(role=role)
        images = raw.get("images", ())
        if not isinstance(images, (list, tuple)):
            images = ()
        clean_images = tuple(
            str(value) for value in images
            if isinstance(value, str) and value.strip()
        )
        return cls(
            role=role,
            images=clean_images,
            fit_mode=normalize_fit_mode(raw.get("fit_mode", "fit")),
            alignment=normalize_alignment(raw.get("alignment", "center")),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "images": list(self.images),
            "fit_mode": self.fit_mode,
            "alignment": self.alignment,
        }


class ImageSetStore:
    """App-owned image-set storage without changing canonical repository assets.

    Imported files are copied beneath ``root/roles/<role>``.  The manifest only
    stores app-relative paths so moving the user's profile does not break sets.
    Missing or corrupt entries are ignored at resolution time.
    """

    SCHEMA_VERSION = 1

    def __init__(self, root: Path):
        self.root = Path(root)
        self.roles_dir = self.root / "roles"
        self.manifest_path = self.root / "image_sets.json"
        self._cache: dict[str, tuple[tuple[tuple[str, int, int], ...], tuple[Path, ...]]] = {}

    def _safe_role(self, role: str) -> str:
        clean = "".join(ch for ch in str(role) if ch.isalnum() or ch in {"_", "-"})
        return clean or "default"

    def _load_manifest(self) -> dict[str, object]:
        if not self.manifest_path.is_file():
            return {"schema_version": self.SCHEMA_VERSION, "roles": {}}
        try:
            raw = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"schema_version": self.SCHEMA_VERSION, "roles": {}}
        if not isinstance(raw, dict) or not isinstance(raw.get("roles"), dict):
            return {"schema_version": self.SCHEMA_VERSION, "roles": {}}
        return raw

    def _save_manifest(self, manifest: dict[str, object]) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        manifest["schema_version"] = self.SCHEMA_VERSION
        temp = self.manifest_path.with_name(f"{self.manifest_path.name}.tmp")
        try:
            temp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.manifest_path)
        finally:
            try:
                temp.unlink(missing_ok=True)
            except OSError:
                pass

    def get(self, role: str) -> ImageSetConfig:
        role = self._safe_role(role)
        manifest = self._load_manifest()
        roles = manifest.get("roles", {})
        return ImageSetConfig.from_dict(role, roles.get(role, {}))

    def set_options(self, role: str, *, fit_mode: str | None = None, alignment: str | None = None) -> ImageSetConfig:
        role = self._safe_role(role)
        manifest = self._load_manifest()
        roles = manifest.setdefault("roles", {})
        current = ImageSetConfig.from_dict(role, roles.get(role, {}))
        updated = ImageSetConfig(
            role=role,
            images=current.images,
            fit_mode=normalize_fit_mode(current.fit_mode if fit_mode is None else fit_mode),
            alignment=normalize_alignment(current.alignment if alignment is None else alignment),
        )
        roles[role] = updated.to_dict()
        self._save_manifest(manifest)
        self.invalidate(role)
        return updated

    def import_files(self, role: str, paths: Iterable[Path]) -> ImageSetConfig:
        role = self._safe_role(role)
        role_dir = self.roles_dir / role
        role_dir.mkdir(parents=True, exist_ok=True)

        manifest = self._load_manifest()
        roles = manifest.setdefault("roles", {})
        current = ImageSetConfig.from_dict(role, roles.get(role, {}))
        stored = list(current.images)

        for source in paths:
            source = Path(source).expanduser()
            if not is_supported_image(source):
                continue
            suffix = source.suffix.lower()
            target = role_dir / f"{uuid.uuid4().hex}{suffix}"
            shutil.copy2(source, target)
            stored.append(target.relative_to(self.root).as_posix())

        updated = ImageSetConfig(
            role=role,
            images=tuple(stored),
            fit_mode=current.fit_mode,
            alignment=current.alignment,
        )
        roles[role] = updated.to_dict()
        self._save_manifest(manifest)
        self.invalidate(role)
        return updated

    def import_folder(self, role: str, folder: Path) -> ImageSetConfig:
        folder = Path(folder).expanduser()
        if not folder.is_dir():
            return self.get(role)
        paths = sorted(
            (path for path in folder.iterdir() if is_supported_image(path)),
            key=lambda path: path.name.lower(),
        )
        return self.import_files(role, paths)

    def clear(self, role: str, *, delete_files: bool = True) -> ImageSetConfig:
        role = self._safe_role(role)
        manifest = self._load_manifest()
        roles = manifest.setdefault("roles", {})
        current = ImageSetConfig.from_dict(role, roles.get(role, {}))
        roles[role] = ImageSetConfig(role=role, fit_mode=current.fit_mode, alignment=current.alignment).to_dict()
        self._save_manifest(manifest)
        if delete_files:
            role_dir = self.roles_dir / role
            if role_dir.is_dir():
                shutil.rmtree(role_dir, ignore_errors=True)
        self.invalidate(role)
        return self.get(role)

    def _resolved_with_signature(self, role: str) -> tuple[tuple[tuple[str, int, int], ...], tuple[Path, ...]]:
        config = self.get(role)
        signature_items: list[tuple[str, int, int]] = []
        resolved: list[Path] = []
        for relative in config.images:
            path = (self.root / relative).resolve()
            try:
                path.relative_to(self.root.resolve())
            except ValueError:
                continue
            if not is_supported_image(path):
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            signature_items.append((relative, stat.st_mtime_ns, stat.st_size))
            resolved.append(path)
        return tuple(signature_items), tuple(resolved)

    def list_images(self, role: str) -> tuple[Path, ...]:
        role = self._safe_role(role)
        signature, resolved = self._resolved_with_signature(role)
        cached = self._cache.get(role)
        if cached and cached[0] == signature:
            return cached[1]
        self._cache[role] = (signature, resolved)
        return resolved

    def choose(self, role: str, rng: random.Random | None = None) -> Path | None:
        images = self.list_images(role)
        if not images:
            return None
        chooser = rng or random
        return chooser.choice(images)

    def invalidate(self, role: str | None = None) -> None:
        if role is None:
            self._cache.clear()
        else:
            self._cache.pop(self._safe_role(role), None)
