"""Bundled, process-private desktop fonts and explicit Tk fallbacks.

Register before creating Tk: Windows then sees the private faces when it first
enumerates fonts. No administrator access or permanent font installation is used.
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from pathlib import Path
import sys
import tkinter as tk
import tkinter.font as tkfont


FONT_FILES = (
    "Pretendard-Regular.otf", "Pretendard-Medium.otf",
    "Pretendard-SemiBold.otf", "Pretendard-Bold.otf",
)
_registered_paths: set[str] = set()
_log = logging.getLogger("kyunghee")


def bundled_font_directory() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "assets" / "fonts"


def register_bundled_fonts() -> int:
    """Make bundled faces available for this process, tolerating missing fonts."""
    paths = [bundled_font_directory() / name for name in FONT_FILES]
    pending = [p for p in paths if p.is_file() and str(p) not in _registered_paths]
    if not pending:
        return 0
    loaded = 0
    try:
        if os.name == "nt":
            add_font = ctypes.WinDLL("gdi32", use_last_error=True).AddFontResourceExW
            add_font.argtypes = (ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p)
            add_font.restype = ctypes.c_int
            for path in pending:
                if add_font(str(path), 0x10, None):  # FR_PRIVATE: process lifetime only.
                    _registered_paths.add(str(path))
                    loaded += 1
        elif sys.platform.startswith("linux"):
            # This also makes Linux development previews match the Windows UI.
            library = ctypes.util.find_library("fontconfig")
            if library:
                fc = ctypes.CDLL(library)
                fc.FcConfigGetCurrent.restype = ctypes.c_void_p
                fc.FcConfigAppFontAddFile.argtypes = (ctypes.c_void_p, ctypes.c_char_p)
                fc.FcConfigAppFontAddFile.restype = ctypes.c_int
                config = fc.FcConfigGetCurrent()
                for path in pending:
                    if fc.FcConfigAppFontAddFile(config, os.fsencode(path)):
                        _registered_paths.add(str(path))
                        loaded += 1
    except (OSError, AttributeError):
        _log.warning("Bundled font registration unavailable; using a system font")
    return loaded


def resolve_font_family(root, role: str = "body") -> str:
    """Return an installed family for a semantic UI role, never a guessed face."""
    try:
        available = getattr(root, "_kyunghee_font_families", None)
        if available is None:
            available = {name.casefold(): name for name in tkfont.families(root)}
            root._kyunghee_font_families = available
        preferred = {
            "controls": ("Pretendard Medium", "Pretendard"),
            "title": ("Pretendard SemiBold", "Pretendard",),
            "timer": ("Pretendard SemiBold", "Pretendard",),
        }.get(role, ("Pretendard", "Pretendard Regular"))
        for name in (*preferred, "Malgun Gothic", "Noto Sans CJK KR", "Noto Sans KR",
                     "Apple SD Gothic Neo", "Segoe UI", "DejaVu Sans"):
            if name.casefold() in available:
                return available[name.casefold()]
        return tkfont.nametofont("TkDefaultFont", root=root).actual("family")
    except tk.TclError:
        return "Malgun Gothic" if os.name == "nt" else "sans-serif"


def ui_font(root, size: int = 10, role: str = "body", weight: str | None = None) -> tuple[str, int, str]:
    """Build a Tk font tuple; explicit Medium/SemiBold faces need normal weight."""
    if weight == "bold" and role in ("body", "status", "controls"):
        role = "title"
    family = resolve_font_family(root, role)
    face_has_weight = family.casefold() in ("pretendard medium", "pretendard semibold")
    tk_weight = "normal" if face_has_weight else (
        "bold" if weight == "bold" or role in ("timer", "title") else "normal"
    )
    return family, int(size), tk_weight
