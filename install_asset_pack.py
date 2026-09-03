from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox

ROOT = Path(__file__).resolve().parent
ASSET_DIR = ROOT / "assets"
CANONICAL = {
    "main_kyunghee.png",
    "stats_kyunghee.png",
    "settings_kyunghee.png",
    "alert_kyunghee.png",
    "away_kyunghee.png",
    "focus_cheer_kyunghee.png",
    "rest_suggest_kyunghee.png",
    "leave_work_kyunghee.png",
    "warning_kyunghee.png",
    "profile_kyunghee.png",
}


def install_from_zip(zip_path: Path) -> list[str]:
    ASSET_DIR.mkdir(parents=True, exist_ok=True)
    installed: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            name = Path(info.filename).name
            if name not in CANONICAL:
                continue
            target = ASSET_DIR / name
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

    missing = sorted(CANONICAL - set(installed))
    if missing:
        messagebox.showwarning(
            "에셋 일부 누락",
            "설치된 파일: %d개\n누락: %s" % (len(installed), ", ".join(missing)),
        )
        return 3

    messagebox.showinfo("에셋 설치 완료", f"확정 PNG 에셋 {len(installed)}개를 assets 폴더에 설치했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
