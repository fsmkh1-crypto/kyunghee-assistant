from __future__ import annotations

from pathlib import Path
from typing import Iterable

ASSET_DIR = Path(__file__).resolve().parent / "assets"

# Canonical desktop asset pack.
#
# New UI work uses explicit PNG masters so the same approved images are reused
# across screens instead of being regenerated or depending on fragile WebP
# placeholders. Legacy names remain as fallbacks until the PNG pack is copied
# into the repository/runtime bundle.
ROLE_FILES = {
    "default": (
        "main_kyunghee.png",
        "default_full.webp", "default_full.png", "default_full.jpg",
    ),
    "playful": (
        "main_kyunghee.png",
        "playful.webp", "playful.png", "playful.jpg",
    ),
    "cheer": (
        "focus_cheer_kyunghee.png",
        "cheer_full.webp", "cheer.webp",
        "cheer_full.png", "cheer.png",
        "cheer_full.jpg", "cheer.jpg",
    ),
    "cute_cheer": (
        "focus_cheer_kyunghee.png",
        "cute_cheer.webp", "cute_cheer.png", "cute_cheer.jpg",
    ),
    "rest": (
        "rest_suggest_kyunghee.png",
        "worry.webp", "worry.png", "worry.jpg",
    ),
    "away": (
        "away_kyunghee.png",
        "worry.webp", "worry.png", "worry.jpg",
    ),
    "worry": (
        "warning_kyunghee.png",
        "worry.webp", "worry.png", "worry.jpg",
    ),
    "nag": (
        "warning_kyunghee.png",
        "nag.webp", "nag.png", "nag.jpg",
    ),
    "praise": (
        "leave_work_kyunghee.png",
        "praise.webp", "praise.png", "praise.jpg",
    ),
    "stats": (
        "stats_kyunghee.png",
        "focus_cheer_kyunghee.png",
        "cheer_full.webp", "cheer.webp",
    ),
    "settings": (
        "settings_kyunghee.png",
        "main_kyunghee.png",
        "default_full.webp",
    ),
    "alert": (
        "alert_kyunghee.png",
        "focus_cheer_kyunghee.png",
        "cheer_full.webp",
    ),
    "master_face": (
        "profile_kyunghee.png",
        # Keep the valid playful portrait ahead of the known-truncated legacy
        # master_face.png when the approved profile PNG is unavailable.
        "playful.webp",
        "master_face.webp", "master_face.png", "master_face.jpg",
    ),
}

WORK_MODE_ROLE = {
    "normal": "default",
    "wind_down": "rest",
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
    "away_start": "away",
    "break": "rest",
    "snooze1": "rest",
    "snooze2": "nag",
    "stats": "stats",
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
