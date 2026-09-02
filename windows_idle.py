from __future__ import annotations
import ctypes
import os

if os.name != "nt":
    def last_input_info() -> tuple[float, int]:
        return 0.0, 0
else:
    _user32 = ctypes.windll.user32
    _k32 = ctypes.windll.kernel32

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

    _k32.GetTickCount64.restype = ctypes.c_ulonglong
    _user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
    _user32.GetLastInputInfo.restype = ctypes.c_int

    def last_input_info() -> tuple[float, int]:
        lii = LASTINPUTINFO()
        lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not _user32.GetLastInputInfo(ctypes.byref(lii)):
            return 0.0, 0
        now64 = int(_k32.GetTickCount64())
        idle_ms = (now64 - int(lii.dwTime)) & 0xFFFFFFFF
        return max(0.0, idle_ms / 1000.0), int(lii.dwTime)
