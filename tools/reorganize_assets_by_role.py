from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"

MOVES = {
    "default": ["main_kyunghee.png", "default_full.webp", "playful.webp"],
    "cheer": ["focus_cheer_kyunghee.png", "cheer_full.webp", "cheer.webp", "cute_cheer.webp"],
    "rest": ["rest_suggest_kyunghee.png"],
    "away": ["away_kyunghee.png"],
    "warning": ["warning_kyunghee.png", "nag.webp", "worry.webp"],
    "leave": ["leave_work_kyunghee.png", "praise.webp"],
    "stats": ["stats_kyunghee.png"],
    "settings": ["settings_kyunghee.png"],
    "alert": ["alert_kyunghee.png"],
    "profile": ["profile_kyunghee.png", "master_face.png"],
}

for folder, names in MOVES.items():
    target_dir = ASSETS / folder
    target_dir.mkdir(parents=True, exist_ok=True)
    for name in names:
        src = ASSETS / name
        dst = target_dir / name
        if src.exists():
            if dst.exists():
                raise SystemExit(f"destination already exists: {dst}")
            shutil.move(str(src), str(dst))

asset_manager = '''from __future__ import annotations

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
'''
(ROOT / "asset_manager.py").write_text(asset_manager, encoding="utf-8")

installer = '''from __future__ import annotations

import shutil
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
CANONICAL = {
    "main_kyunghee.png": "default",
    "focus_cheer_kyunghee.png": "cheer",
    "rest_suggest_kyunghee.png": "rest",
    "away_kyunghee.png": "away",
    "warning_kyunghee.png": "warning",
    "leave_work_kyunghee.png": "leave",
    "stats_kyunghee.png": "stats",
    "settings_kyunghee.png": "settings",
    "alert_kyunghee.png": "alert",
    "profile_kyunghee.png": "profile",
}


def install_from_zip(zip_path: Path) -> list[str]:
    installed: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            folder = CANONICAL.get(name)
            if not folder:
                continue
            target_dir = ASSET_DIR / folder
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / name
            with zf.open(info) as src, target.open("wb") as dst:
                shutil.copyfileobj(src, dst)
            installed.append(name)
    return sorted(installed)


def main() -> int:
    root = tk.Tk()
    root.withdraw()
    root.update_idletasks()
    initial = Path.home() / "Downloads"
    selected = filedialog.askopenfilename(
        title="경희 타이머 확정 에셋 ZIP 선택",
        initialdir=str(initial if initial.exists() else Path.home()),
        filetypes=[("ZIP files", "*.zip"), ("All files", "*.*")],
    )
    if not selected:
        return 1
    try:
        installed = install_from_zip(Path(selected))
    except Exception as exc:
        messagebox.showerror("에셋 설치 실패", str(exc))
        return 2
    missing = sorted(set(CANONICAL) - set(installed))
    if missing:
        messagebox.showwarning("에셋 일부 누락", "설치된 파일: %d개\\n누락: %s" % (len(installed), ", ".join(missing)))
        return 3
    messagebox.showinfo("에셋 설치 완료", f"확정 PNG 에셋 {len(installed)}개를 역할별 assets 폴더에 설치했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''
(ROOT / "install_asset_pack.py").write_text(installer, encoding="utf-8")

readme = '''# Character asset contract

The approved Kyunghee assets are organized by user-facing role. Do not regenerate or replace approved masters without explicit instruction.

## Folder layout

- `default/` — normal / playful
- `cheer/` — focus encouragement / cute cheer
- `rest/` — break suggestion
- `away/` — away state
- `warning/` — worry / nag / late-work warnings
- `leave/` — leave-work / praise
- `stats/` — stats screen
- `settings/` — settings screen
- `alert/` — alert/toast artwork
- `profile/` — profile / identity face

Root-level `README.md`, `atlas_manifest.json`, and compatibility metadata stay in `assets/`.

## Approved masters

- `default/main_kyunghee.png`
- `cheer/focus_cheer_kyunghee.png`
- `rest/rest_suggest_kyunghee.png`
- `away/away_kyunghee.png`
- `warning/warning_kyunghee.png`
- `leave/leave_work_kyunghee.png`
- `stats/stats_kyunghee.png`
- `settings/settings_kyunghee.png`
- `alert/alert_kyunghee.png`
- `profile/profile_kyunghee.png`

Legacy compatibility files are kept in the closest matching role folder. `asset_manager.py` resolves the role-folder path first and still accepts the old flat layout as a fallback for older external packs.

## Naming rule for future additions

Prefer `<role>_01.png`, `<role>_02.png`, etc. Add a short semantic suffix only when useful, e.g. `cheer_thumbsup_01.png`.

Full-body artwork must preserve aspect ratio and visible legs. Future poses should preserve the same canonical identity direction as the approved profile/master assets.
'''
(ASSETS / "README.md").write_text(readme, encoding="utf-8")

runtime_test = '''import unittest
from pathlib import Path

from asset_manager import ASSET_DIR, ROLE_FILES, resolve_asset, role_for_dialogue, role_for_work_mode


class RuntimeAssetTests(unittest.TestCase):
    def test_every_character_role_resolves_to_committed_file(self):
        for role in ROLE_FILES:
            with self.subTest(role=role):
                path = resolve_asset(role)
                self.assertIsNotNone(path)
                self.assertTrue(path.is_file())
                self.assertTrue(path.is_relative_to(ASSET_DIR))
                self.assertNotEqual(path.parent, ASSET_DIR)

    def test_role_folders_are_used_for_canonical_assets(self):
        expected = {
            "default": "default/main_kyunghee.png",
            "cheer": "cheer/focus_cheer_kyunghee.png",
            "rest": "rest/rest_suggest_kyunghee.png",
            "away": "away/away_kyunghee.png",
            "worry": "warning/warning_kyunghee.png",
            "nag": "warning/warning_kyunghee.png",
            "praise": "leave/leave_work_kyunghee.png",
            "stats": "stats/stats_kyunghee.png",
            "settings": "settings/settings_kyunghee.png",
            "alert": "alert/alert_kyunghee.png",
            "master_face": "profile/profile_kyunghee.png",
        }
        for role, relative in expected.items():
            with self.subTest(role=role):
                self.assertEqual(ROLE_FILES[role][0], relative)
                self.assertEqual(resolve_asset(role), ASSET_DIR / relative)

    def test_workday_visual_policy(self):
        self.assertEqual(role_for_work_mode("normal"), "default")
        self.assertEqual(role_for_work_mode("wind_down"), "rest")
        self.assertEqual(role_for_work_mode("leave"), "praise")
        self.assertEqual(role_for_work_mode("strong_leave"), "nag")
        self.assertEqual(role_for_work_mode("late_leave"), "nag")
        self.assertEqual(role_for_work_mode("hard_stop"), "nag")

    def test_dialogue_visual_policy(self):
        self.assertEqual(role_for_dialogue("return"), "cute_cheer")
        self.assertEqual(role_for_dialogue("away_start"), "away")
        self.assertEqual(role_for_dialogue("snooze1"), "rest")
        self.assertEqual(role_for_dialogue("snooze2"), "nag")
        self.assertEqual(role_for_dialogue("stats"), "stats")
        self.assertEqual(role_for_dialogue("break", "leave"), "praise")


if __name__ == "__main__":
    unittest.main()
'''
(ROOT / "tests" / "test_runtime_assets.py").write_text(runtime_test, encoding="utf-8")

asset_test = (ROOT / "tests" / "test_asset_manager.py").read_text(encoding="utf-8")
old = '''            (root / "nag.jpg").write_bytes(b"x")\n            self.assertEqual(resolve_asset("nag", root), root / "nag.jpg")\n            (root / "warning_kyunghee.png").write_bytes(b"x")\n            self.assertEqual(resolve_asset("nag", root), root / "warning_kyunghee.png")\n'''
new = '''            (root / "nag.jpg").write_bytes(b"x")\n            self.assertEqual(resolve_asset("nag", root), root / "nag.jpg")\n            (root / "warning").mkdir()\n            (root / "warning" / "warning_kyunghee.png").write_bytes(b"x")\n            self.assertEqual(resolve_asset("nag", root), root / "warning" / "warning_kyunghee.png")\n'''
if old not in asset_test:
    raise SystemExit("test_asset_manager patch target missing")
(ROOT / "tests" / "test_asset_manager.py").write_text(asset_test.replace(old, new), encoding="utf-8")

print("role-based asset layout applied")
