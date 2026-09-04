from __future__ import annotations

from pathlib import Path
import random
import re
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

# Built-in numbered assets are complete wardrobe/identity sets. Pick one set
# for the process and keep the number consistent across every runtime role.
VARIANT_ROLE = {
    "default": "default",
    "playful": "default",
    "cheer": "cheer",
    "cute_cheer": "cheer",
    "rest": "rest",
    "away": "away",
    "worry": "warning",
    "nag": "warning",
    "praise": "leave",
    "stats": "stats",
    "settings": "settings",
    "alert": "alert",
    "master_face": "profile",
}
VARIANT_FOLDERS = tuple(dict.fromkeys(VARIANT_ROLE.values()))
_VARIANT_PATTERN = re.compile(r"^(?P<role>[a-z_]+)_(?P<set>\d{2})\.png$")
_SESSION_SET_BY_ROOT: dict[Path, int | None] = {}

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


def _root_key(asset_dir: Path) -> Path:
    try:
        return Path(asset_dir).resolve()
    except OSError:
        return Path(asset_dir).absolute()


def available_complete_sets(asset_dir: Path = ASSET_DIR) -> tuple[int, ...]:
    """Return numbered sets that contain all ten built-in role images."""
    root = Path(asset_dir)
    per_role: list[set[int]] = []
    for role in VARIANT_FOLDERS:
        folder = root / role
        numbers: set[int] = set()
        if folder.is_dir():
            for path in folder.glob(f"{role}_[0-9][0-9].png"):
                match = _VARIANT_PATTERN.match(path.name)
                if match and match.group("role") == role and path.is_file():
                    numbers.add(int(match.group("set")))
        per_role.append(numbers)
    if not per_role:
        return ()
    complete = set.intersection(*per_role)
    return tuple(sorted(complete))


def variant_asset(role: str, set_number: int, asset_dir: Path = ASSET_DIR) -> Path | None:
    variant_role = VARIANT_ROLE.get(role)
    if variant_role is None or not 1 <= int(set_number) <= 99:
        return None
    path = Path(asset_dir) / variant_role / f"{variant_role}_{int(set_number):02d}.png"
    return path if path.is_file() else None


def select_session_set(
    asset_dir: Path = ASSET_DIR,
    *,
    rng: random.Random | None = None,
) -> int | None:
    """Choose one complete built-in set and keep it stable for this process."""
    key = _root_key(asset_dir)
    if key in _SESSION_SET_BY_ROOT:
        return _SESSION_SET_BY_ROOT[key]
    complete = available_complete_sets(asset_dir)
    selected = (rng or random).choice(complete) if complete else None
    _SESSION_SET_BY_ROOT[key] = selected
    return selected


def set_session_set(set_number: int | None, asset_dir: Path = ASSET_DIR) -> None:
    """Override/reset the process-wide built-in set; primarily useful for tests."""
    key = _root_key(asset_dir)
    if set_number is None:
        _SESSION_SET_BY_ROOT.pop(key, None)
        return
    set_number = int(set_number)
    if set_number not in available_complete_sets(asset_dir):
        raise ValueError(f"built-in asset set {set_number:02d} is incomplete or missing")
    _SESSION_SET_BY_ROOT[key] = set_number


def resolve_asset(role: str, asset_dir: Path = ASSET_DIR) -> Path | None:
    # User-imported image sets are resolved before this function by the desktop
    # UI. Here, prefer one coherent built-in numbered set, then canonical/legacy.
    set_number = select_session_set(asset_dir)
    if set_number is not None:
        numbered = variant_asset(role, set_number, asset_dir)
        if numbered is not None:
            return numbered
    names = ROLE_FILES.get(role, ROLE_FILES["default"])
    return first_existing(names, asset_dir)


def role_for_work_mode(mode: str) -> str:
    return WORK_MODE_ROLE.get(mode, "default")


def role_for_dialogue(kind: str, work_mode: str = "normal") -> str:
    if work_mode != "normal":
        return role_for_work_mode(work_mode)
    return DIALOGUE_ROLE.get(kind, "default")
