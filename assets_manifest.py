from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AssetSpec:
    filename: str
    role: str


ASSETS = {
    "default": AssetSpec("default_full.png", "main/default playful pose"),
    "cheer": AssetSpec("cheer_full.png", "stats / fighting pose"),
    "cute_cheer": AssetSpec("cute_cheer.png", "short praise / return"),
    "nag": AssetSpec("nag.png", "repeated snooze / late-work nagging"),
    "worry": AssetSpec("worry.png", "first snooze / long-session concern"),
    "praise": AssetSpec("praise.png", "good break / daily praise"),
    "playful": AssetSpec("playful.png", "compact normal toast"),
    "master_face": AssetSpec("master_face.png", "tray / compact neutral toast"),
}

WORK_MODE_ASSET = {
    "normal": "default",
    "wind_down": "worry",
    "leave": "praise",
    "strong_leave": "nag",
    "late_leave": "nag",
    "hard_stop": "nag",
}


def asset_for_work_mode(mode: str) -> str:
    return WORK_MODE_ASSET.get(mode, "default")
