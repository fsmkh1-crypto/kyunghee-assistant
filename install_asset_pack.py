from __future__ import annotations

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
        messagebox.showwarning("에셋 일부 누락", "설치된 파일: %d개\n누락: %s" % (len(installed), ", ".join(missing)))
        return 3
    messagebox.showinfo("에셋 설치 완료", f"확정 PNG 에셋 {len(installed)}개를 역할별 assets 폴더에 설치했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
