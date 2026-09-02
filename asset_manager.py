from __future__ import annotations

from pathlib import Path
from typing import Iterable

ASSET_DIR = Path(__file__).resolve().parent / "assets"

# Runtime assets committed to the repository are compact WebP files. PNG/JPG
# names remain as compatibility fallbacks for older local asset packs.
ROLE_FILES = {
    "default": ("default_full.webp", "default_full.png", "default_full.jpg"),
    "playful": ("playful.webp", "playful.png", "playful.jpg"),
    "cheer": (
        "cheer_full.webp", "cheer.webp",
        "cheer_full.png", "cheer.png",
        "cheer_full.jpg", "cheer.jpg",
    ),
    "cute_cheer": ("cute_cheer.webp", "cute_cheer.png", "cute_cheer.jpg"),
    "nag": ("nag.webp", "nag.png", "nag.jpg"),
    "worry": ("worry.webp", "worry.png", "worry.jpg"),
    "praise": ("praise.webp", "praise.png", "praise.jpg"),
    "master_face": ("master_face.png", "master_face.webp", "master_face.jpg"),
}

WORK_MODE_ROLE = {
    "normal": "default",
    "wind_down": "worry",
    "leave": "praise",
    "strong_leave": "nag",
    "late_leave": "nag",
    "hard_stop": "nag",
}

DIALOGUE_ROLE = {
    "playful": "playful",
    "cheer": "cheer",
    "cute_cheer": "cute_cheer",
    "worry": "worry",
    "nag": "nag",
    "praise": "praise",
    "return": "cute_cheer",
    "away_start": "worry",
    "break": "worry",
    "snooze1": "worry",
    "snooze2": "nag",
    "stats": "cheer",
}


def first_existing(names: Iterable[str], asset_dir: Path = ASSET_DIR) -> Path | None:
    for name in names:
        path = asset_dir / name
        if path.is_file():
            return path
    return None


def resolve_asset(role: str, asset_dir: Path = ASSET_DIR) -> Path | None:
    names = ROLE_FILES.get(role, ROLE_FILES["default"])
    return first_existing(names, asset_dir)


def role_for_work_mode(mode: str) -> str:
    return WORK_MODE_ROLE.get(mode, "default")


def role_for_dialogue(kind: str, work_mode: str = "normal") -> str:
    if work_mode != "normal":
        return role_for_work_mode(work_mode)
    return DIALOGUE_ROLE.get(kind, "default")
