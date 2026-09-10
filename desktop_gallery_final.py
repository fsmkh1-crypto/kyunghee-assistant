from __future__ import annotations

import hashlib
import os
from pathlib import Path

import app as core
import asset_manager
import desktop_compact as compact
import desktop_gallery as gallery
from asset_rotation import raw_complete_sets


# The global set dropdown is a manual selector, so it must still expose every
# physical complete set (including exact duplicate set 09 and restored set 10).
# Only automatic random rotation deduplicates exact whole-set copies.
asset_manager.available_complete_sets = raw_complete_sets
compact.available_complete_sets = raw_complete_sets


class FinalGalleryDesktopApp(gallery.GalleryDesktopApp):
    """Final settings-gallery entry point with manual duplicate visibility."""

    def __init__(self):
        self._random_refs_signature = None
        self._random_refs_cache: list[str] = []
        super().__init__()

    @staticmethod
    def _prefer_duplicate_candidate(existing: Path, candidate: Path) -> bool:
        """Prefer restored set 10 over byte-identical set 09 for auto-random use."""
        existing_name = existing.stem.lower()
        candidate_name = candidate.stem.lower()
        if existing_name.endswith('_09') and candidate_name.endswith('_10'):
            return True
        return False

    def _catalog_refs(self):
        """Random pool uses every unique image once; manual gallery keeps duplicates."""
        entries = self._catalog()
        signature = []
        for _group, _label, path in entries:
            try:
                stat = path.stat()
                signature.append((str(path), stat.st_mtime_ns, stat.st_size))
            except OSError:
                signature.append((str(path), 0, 0))
        signature = tuple(signature)
        if signature == self._random_refs_signature:
            return list(self._random_refs_cache)

        by_digest: dict[str, tuple[Path, str]] = {}
        for _group, _label, path in entries:
            try:
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                continue
            ref = self._encode_asset_ref(path)
            previous = by_digest.get(digest)
            if previous is None or self._prefer_duplicate_candidate(previous[0], path):
                by_digest[digest] = (path, ref)

        refs = [ref for _path, ref in by_digest.values()]
        self._random_refs_signature = signature
        self._random_refs_cache = list(refs)
        return refs

    def _refresh_runtime_role_for_key(self, key: str) -> None:
        current_role = getattr(self, 'character_role', None)
        if current_role and self.ROLE_TO_SETTING.get(current_role, 'default') == key:
            self.character_role = None
            self._set_character(current_role)
            self._apply_widget_appearance()

    def _follow_selected_set(self, key: str) -> None:
        super()._follow_selected_set(key)
        self._refresh_runtime_role_for_key(key)

    def _reset_image(self, key):
        super()._reset_image(key)
        self._refresh_runtime_role_for_key(key)


if __name__ == '__main__':
    if os.name != 'nt':
        raise SystemExit('Windows only')
    compact.enable_per_monitor_dpi_awareness()
    singleton = compact.SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    FinalGalleryDesktopApp().run()
