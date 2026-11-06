"""Standalone AI review executable with data and instance isolation."""
from __future__ import annotations

import ctypes
import os
from pathlib import Path
import tempfile

REVIEW_FOLDER = "KyungheeTimer_AI_Review"
REVIEW_MUTEX = "Local\\KyungheeTimerAIReviewSingleton"


def review_appdata(environ=None) -> Path:
    values = os.environ if environ is None else environ
    base = values.get("LOCALAPPDATA") or values.get("TEMP") or tempfile.gettempdir()
    return Path(base) / REVIEW_FOLDER


class ReviewSingleInstance:
    """Do not share the stable app's mutex or its user-data directory."""

    def __init__(self):
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        self.handle = kernel.CreateMutexW(None, False, REVIEW_MUTEX)
        return bool(self.handle) and ctypes.get_last_error() != 183


def main():
    if os.name != "nt":
        raise SystemExit("Windows only")
    # app.py computes all persistence locations at import time. Set this first,
    # including when the EXE is double-clicked or renamed by the user.
    os.environ["APPDATA"] = str(review_appdata())
    from desktop_compact import enable_per_monitor_dpi_awareness
    from desktop_gallery_final import FinalGalleryDesktopApp

    enable_per_monitor_dpi_awareness()
    singleton = ReviewSingleInstance()
    if not singleton.acquire():
        return
    app = FinalGalleryDesktopApp()
    app.root.title("승아 타이머 · AI 연결 테스트")
    app.run()


if __name__ == "__main__":
    main()
