from __future__ import annotations

from pathlib import Path
from typing import Iterable

ASSET_DIR = Path(__file__).resolve().parent / "assets"

ROLE_FILES = {
    "default": (
        "default/main_kyunghee.png",
        "default/default_full.webp", "default/default_full.png", "default/default_full.jpg",
    ),
    "playful": (
        "default/main_kyunghee.png",
        "default/playful.webp", "default/playful.png", "default/playful.jpg",
    ),
    "cheer": (
        "cheer/focus_cheer_kyunghee.png",
        "cheer/cheer_full.webp", "cheer/cheer.webp",
        "cheer/cheer_full.png", "cheer/cheer.png",
        "cheer/cheer_full.jpg", "cheer/cheer.jpg",
    ),
    "cute_cheer": (
        "cheer/focus_cheer_kyunghee.png",
        "cheer/cute_cheer.webp", "cheer/cute_cheer.png", "cheer/cute_cheer.jpg",
    ),
    "rest": (
        "rest/rest_suggest_kyunghee.png",
        "warning/worry.webp", "warning/worry.png", "warning/worry.jpg",
    ),
    "away": (
        "away/away_kyunghee.png",
        "warning/worry.webp", "warning/worry.png", "warning/worry.jpg",
    ),
    "worry": (
        "warning/warning_kyunghee.png",
        "warning/worry.webp", "warning/worry.png", "warning/worry.jpg",
    ),
    "nag": (
        "warning/warning_kyunghee.png",
        "warning/nag.webp", "warning/nag.png", "warning/nag.jpg",
    ),
    "praise": (
        "leave/leave_work_kyunghee.png",
        "leave/praise.webp", "leave/praise.png", "leave/praise.jpg",
    ),
    "stats": (
        "stats/stats_kyunghee.png",
        "cheer/focus_cheer_kyunghee.png",
        "cheer/cheer_full.webp", "cheer/cheer.webp",
    ),
    "settings": (
        "settings/settings_kyunghee.png",
        "default/main_kyunghee.png",
        "default/default_full.webp",
    ),
    "alert": (
        "alert/alert_kyunghee.png",
        "cheer/focus_cheer_kyunghee.png",
        "cheer/cheer_full.webp",
    ),
    "master_face": (
        "profile/profile_kyunghee.png",
        "default/playful.webp",
        "profile/master_face.webp", "profile/master_face.png", "profile/master_face.jpg",
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
        legacy = asset_dir / Path(name).name
        if legacy.is_file():
            return legacy
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
