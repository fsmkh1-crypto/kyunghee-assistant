from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import sys
import time

from PIL import Image


DEFAULT_ASSET = Path("assets") / "away" / "away_02.png"
DEFAULT_MAX_SIZE = (346, 384)


def resource_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if frozen_root:
        return Path(frozen_root)
    return Path(__file__).resolve().parents[1]


def resolve_asset_path(value: str | Path | None) -> Path:
    path = Path(value) if value else DEFAULT_ASSET
    if path.is_absolute():
        return path
    candidate = resource_root() / path
    if candidate.is_file():
        return candidate
    return path.resolve()


def prepare_image(path: Path, max_size: tuple[int, int]) -> Image.Image:
    with Image.open(path) as src:
        rgba = src.convert("RGBA")
        rgba.thumbnail(max_size, Image.Resampling.LANCZOS)
        return rgba.copy()


def premultiplied_bgra_bytes(image: Image.Image) -> bytes:
    """Return top-to-bottom premultiplied BGRA bytes for UpdateLayeredWindow."""
    premul = image.convert("RGBA").convert("RGBa")
    red, green, blue, alpha = premul.split()
    return Image.merge("RGBA", (blue, green, red, alpha)).tobytes()


if os.name == "nt":
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    WS_POPUP = 0x80000000
    WS_EX_LAYERED = 0x00080000
    WS_EX_TOOLWINDOW = 0x00000080
    WS_EX_TOPMOST = 0x00000008
    SW_SHOWNOACTIVATE = 4
    ULW_ALPHA = 0x00000002
    AC_SRC_OVER = 0x00
    AC_SRC_ALPHA = 0x01
    BI_RGB = 0
    DIB_RGB_COLORS = 0
    WM_DESTROY = 0x0002
    WM_CLOSE = 0x0010
    WM_LBUTTONDOWN = 0x0201
    HTCAPTION = 2
    WM_NCLBUTTONDOWN = 0x00A1

    LRESULT = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        wintypes.WPARAM,
        wintypes.LPARAM,
    )

    class POINT(ctypes.Structure):
        _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]

    class BLENDFUNCTION(ctypes.Structure):
        _fields_ = [
            ("BlendOp", wintypes.BYTE),
            ("BlendFlags", wintypes.BYTE),
            ("SourceConstantAlpha", wintypes.BYTE),
            ("AlphaFormat", wintypes.BYTE),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", wintypes.LONG),
            ("biHeight", wintypes.LONG),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", wintypes.LONG),
            ("biYPelsPerMeter", wintypes.LONG),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    class BITMAPINFO(ctypes.Structure):
        _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.DefWindowProcW.restype = LRESULT
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int
    user32.ReleaseCapture.argtypes = []
    user32.ReleaseCapture.restype = wintypes.BOOL
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = LRESULT
    user32.PeekMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
    user32.PeekMessageW.restype = wintypes.BOOL
    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL
    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT
    user32.UnregisterClassW.argtypes = [wintypes.LPCWSTR, wintypes.HINSTANCE]
    user32.UnregisterClassW.restype = wintypes.BOOL
    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.ATOM
    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND
    user32.UpdateLayeredWindow.argtypes = [
        wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
        wintypes.HDC, ctypes.POINTER(POINT), wintypes.COLORREF,
        ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD,
    ]
    user32.UpdateLayeredWindow.restype = wintypes.BOOL
    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateDIBSection.argtypes = [
        wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD,
    ]
    gdi32.CreateDIBSection.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL


class LayeredAlphaWindow:
    """Small Win32 proof-of-concept window using true per-pixel alpha."""

    def __init__(self, image: Image.Image, *, x: int | None = None, y: int | None = None):
        if os.name != "nt":
            raise RuntimeError("LayeredAlphaWindow is Windows-only")
        self.image = image.convert("RGBA")
        self.width, self.height = self.image.size
        self.x = x
        self.y = y
        self._class_name = f"KyungheeLayeredAlphaPoc_{os.getpid()}"
        self._wndproc = WNDPROC(self._window_proc)
        self._hinstance = kernel32.GetModuleHandleW(None)
        self._hwnd = None
        self._screen_dc = None
        self._memory_dc = None
        self._bitmap = None
        self._old_bitmap = None

    @staticmethod
    def _raise_last_error(action: str):
        code = ctypes.get_last_error()
        raise OSError(code, f"{action} failed: {ctypes.FormatError(code)}")

    def _window_proc(self, hwnd, message, wparam, lparam):
        if message == WM_LBUTTONDOWN:
            user32.ReleaseCapture()
            user32.SendMessageW(hwnd, WM_NCLBUTTONDOWN, HTCAPTION, 0)
            return 0
        if message == WM_CLOSE:
            user32.DestroyWindow(hwnd)
            return 0
        if message == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, message, wparam, lparam)

    def _register_and_create(self):
        window_class = WNDCLASSW()
        window_class.lpfnWndProc = self._wndproc
        window_class.hInstance = self._hinstance
        window_class.lpszClassName = self._class_name
        if not user32.RegisterClassW(ctypes.byref(window_class)):
            self._raise_last_error("RegisterClassW")

        screen_width = user32.GetSystemMetrics(0)
        screen_height = user32.GetSystemMetrics(1)
        x = self.x if self.x is not None else max(0, screen_width - self.width - 48)
        y = self.y if self.y is not None else max(0, (screen_height - self.height) // 2)
        ex_style = WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST
        self._hwnd = user32.CreateWindowExW(
            ex_style,
            self._class_name,
            "Kyunghee per-pixel alpha POC",
            WS_POPUP,
            int(x), int(y), self.width, self.height,
            None, None, self._hinstance, None,
        )
        if not self._hwnd:
            self._raise_last_error("CreateWindowExW")

    def _upload_pixels(self):
        self._screen_dc = user32.GetDC(None)
        if not self._screen_dc:
            self._raise_last_error("GetDC")
        self._memory_dc = gdi32.CreateCompatibleDC(self._screen_dc)
        if not self._memory_dc:
            self._raise_last_error("CreateCompatibleDC")

        info = BITMAPINFO()
        info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        info.bmiHeader.biWidth = self.width
        info.bmiHeader.biHeight = -self.height
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = BI_RGB

        bits = ctypes.c_void_p()
        self._bitmap = gdi32.CreateDIBSection(
            self._screen_dc, ctypes.byref(info), DIB_RGB_COLORS,
            ctypes.byref(bits), None, 0,
        )
        if not self._bitmap or not bits.value:
            self._raise_last_error("CreateDIBSection")
        self._old_bitmap = gdi32.SelectObject(self._memory_dc, self._bitmap)
        pixels = premultiplied_bgra_bytes(self.image)
        ctypes.memmove(bits.value, pixels, len(pixels))

        rect = wintypes.RECT()
        if not user32.GetWindowRect(self._hwnd, ctypes.byref(rect)):
            self._raise_last_error("GetWindowRect")
        destination = POINT(rect.left, rect.top)
        source = POINT(0, 0)
        size = SIZE(self.width, self.height)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        if not user32.UpdateLayeredWindow(
            self._hwnd,
            self._screen_dc,
            ctypes.byref(destination),
            ctypes.byref(size),
            self._memory_dc,
            ctypes.byref(source),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        ):
            self._raise_last_error("UpdateLayeredWindow")

    def close(self):
        if os.name != "nt":
            return
        if self._old_bitmap and self._memory_dc:
            gdi32.SelectObject(self._memory_dc, self._old_bitmap)
            self._old_bitmap = None
        if self._bitmap:
            gdi32.DeleteObject(self._bitmap)
            self._bitmap = None
        if self._memory_dc:
            gdi32.DeleteDC(self._memory_dc)
            self._memory_dc = None
        if self._screen_dc:
            user32.ReleaseDC(None, self._screen_dc)
            self._screen_dc = None
        if self._hwnd and user32.IsWindow(self._hwnd):
            user32.DestroyWindow(self._hwnd)
        self._hwnd = None
        try:
            user32.UnregisterClassW(self._class_name, self._hinstance)
        except Exception:
            pass

    def run(self, *, duration: float = 0.0):
        self._register_and_create()
        self._upload_pixels()
        user32.ShowWindow(self._hwnd, SW_SHOWNOACTIVATE)
        user32.UpdateWindow(self._hwnd)
        started = time.monotonic()
        msg = wintypes.MSG()
        try:
            while self._hwnd and user32.IsWindow(self._hwnd):
                while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 1):
                    if msg.message == 0x0012:
                        return
                    user32.TranslateMessage(ctypes.byref(msg))
                    user32.DispatchMessageW(ctypes.byref(msg))
                if duration > 0 and time.monotonic() - started >= duration:
                    return
                time.sleep(0.01)
        finally:
            self.close()


def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Render one Kyunghee PNG through Win32 UpdateLayeredWindow using true per-pixel alpha.",
    )
    parser.add_argument("--asset", default=str(DEFAULT_ASSET), help="PNG path; defaults to assets/away/away_02.png")
    parser.add_argument("--max-width", type=int, default=DEFAULT_MAX_SIZE[0])
    parser.add_argument("--max-height", type=int, default=DEFAULT_MAX_SIZE[1])
    parser.add_argument("--x", type=int, default=None)
    parser.add_argument("--y", type=int, default=None)
    parser.add_argument("--duration", type=float, default=0.0, help="Auto-close after N seconds; 0 waits until closed")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    if os.name != "nt":
        print("This proof of concept requires Windows.", file=sys.stderr)
        return 2
    asset = resolve_asset_path(args.asset)
    if not asset.is_file():
        print(f"Asset not found: {asset}", file=sys.stderr)
        return 2
    max_size = (max(1, args.max_width), max(1, args.max_height))
    image = prepare_image(asset, max_size)
    window = LayeredAlphaWindow(image, x=args.x, y=args.y)
    window.run(duration=max(0.0, args.duration))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
