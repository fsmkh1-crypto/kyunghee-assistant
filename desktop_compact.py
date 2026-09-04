from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import replace
import os
from pathlib import Path
import shutil
import threading
import tkinter as tk
from tkinter import colorchooser, filedialog
import tkinter.font as tkfont
from PIL import Image, ImageTk

import app as core
from app import SingleInstance
from asset_manager import resolve_asset
from desktop_app import DesktopApp
from image_render import resize_rgba_alpha_safe, threshold_alpha
from messages import pick
from settings import UserSettings, save_user_settings, set_windows_startup, validate_hex_color
from windows_display import enable_per_monitor_dpi_awareness, should_suppress_overlay_notifications


USER_IMAGE_DIR = core.DATA_DIR / "images"
MAX_CUSTOM_IMAGE_DIMENSION = 4000
GLOBAL_HOTKEY_ID = 0x4B48
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
VK_H = 0x48
WM_HOTKEY = 0x0312
PM_REMOVE = 0x0001
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
GA_ROOT = 2


class OutlinedText(tk.Canvas):
    """Text-only widget with a one-pixel outline for transparent Windows surfaces."""

    OFFSETS = (
        (-1, -1), (0, -1), (1, -1),
        (-1, 0),           (1, 0),
        (-1, 1),  (0, 1),  (1, 1),
    )

    def __init__(
        self,
        parent,
        text,
        *,
        family,
        size,
        weight="normal",
        fg,
        outline,
        bg,
        wraplength=0,
        justify="left",
        cursor=None,
    ):
        super().__init__(
            parent,
            bg=bg,
            bd=0,
            highlightthickness=0,
            relief="flat",
            cursor=cursor or "arrow",
        )
        self._font = tkfont.Font(family=family, size=size, weight="normal")
        self._text = text
        self._fg = fg
        self._outline = outline
        self._wraplength = int(wraplength or 0)
        self._justify = justify
        self._outline_items = []
        self._main_item = None
        self._last_geometry_key = None
        self._draw_items()
        self._refresh_geometry(force=True)

    def _text_position(self):
        pad = 3
        if self._justify == "center":
            width = self._wraplength or max(1, self._font.measure(self._text))
            return pad + width / 2, pad, "n"
        return pad, pad, "nw"

    def _item_kwargs(self, fill):
        x, y, anchor = self._text_position()
        kwargs = {
            "text": self._text,
            "font": self._font,
            "fill": fill,
            "anchor": anchor,
            "justify": self._justify,
        }
        if self._wraplength:
            kwargs["width"] = self._wraplength
        return x, y, kwargs

    def _draw_items(self):
        x, y, kwargs = self._item_kwargs(self._outline)
        for dx, dy in self.OFFSETS:
            self._outline_items.append(self.create_text(x + dx, y + dy, **kwargs))
        x, y, kwargs = self._item_kwargs(self._fg)
        self._main_item = self.create_text(x, y, **kwargs)

    def _refresh_geometry(self, force=False):
        geometry_key = (
            self._text,
            self._wraplength,
            self._font.actual("family"),
            self._font.actual("size"),
        )
        if not force and geometry_key == self._last_geometry_key:
            return
        self._last_geometry_key = geometry_key
        bbox = self.bbox("all")
        if not bbox:
            tk.Canvas.configure(self, width=1, height=1)
            return
        width = self._wraplength + 8 if self._wraplength else max(1, bbox[2] - bbox[0] + 6)
        height = max(1, bbox[3] - bbox[1] + 6)
        tk.Canvas.configure(self, width=width, height=height)

    def set_style(self, *, size=None, fg=None, outline=None):
        size_changed = False
        if size is not None:
            new_size = int(size)
            size_changed = int(self._font.actual("size")) != new_size
            self._font.configure(size=new_size, weight="normal")
            for item in self._outline_items:
                self.itemconfigure(item, font=self._font)
            self.itemconfigure(self._main_item, font=self._font)
        if fg is not None:
            self._fg = fg
            self.itemconfigure(self._main_item, fill=fg)
        if outline is not None:
            self._outline = outline
            for item in self._outline_items:
                self.itemconfigure(item, fill=outline)
        if size_changed:
            self._refresh_geometry(force=True)

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        text = kwargs.pop("text", None)
        fg = kwargs.pop("fg", kwargs.pop("foreground", None))
        outline = kwargs.pop("outline", None)
        changed = False
        if text is not None:
            new_text = str(text)
            changed = new_text != self._text
            if changed:
                self._text = new_text
                for item in self._outline_items:
                    self.itemconfigure(item, text=self._text)
                self.itemconfigure(self._main_item, text=self._text)
        if fg is not None or outline is not None:
            self.set_style(fg=fg, outline=outline)
        if kwargs:
            tk.Canvas.configure(self, **kwargs)
        if changed:
            self._refresh_geometry(force=True)

    config = configure

    def cget(self, key):
        if key == "text":
            return self._text
        if key in ("fg", "foreground"):
            return self._fg
        if key == "outline":
            return self._outline
        return tk.Canvas.cget(self, key)

    __getitem__ = cget


def _outline_for(color: str) -> str:
    """Pick a contrasting outline automatically from the chosen text colour."""
    color = validate_hex_color(color)
    rgb = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    luminance = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    if luminance >= 135:
        values = [round(v * 0.43) for v in rgb]
    else:
        values = [round(v + (255 - v) * 0.58) for v in rgb]
    return "#" + "".join(f"{v:02X}" for v in values)


def _intersection_area(rect, area):
    left = max(rect[0], area[0])
    top = max(rect[1], area[1])
    right = min(rect[2], area[2])
    bottom = min(rect[3], area[3])
    return max(0, right - left) * max(0, bottom - top)


class CompactDesktopApp(DesktopApp):
    """Narrow frameless desktop widget using the approved Kyunghee artwork."""

    COMPACT_SIZE = (300, 430)
    DETAIL_SIZE = (410, 430)
    SETTINGS_SIZE = (650, 700)
    CHARACTER_MAX = (346, 384)
    BUBBLE_WRAP = 270
    FONT_FAMILY = "Pretendard"
    ESCAPE_TEXT = "#6B7280"

    IMAGE_ROWS = (
        ("default", "평상시"),
        ("cheer", "집중 응원"),
        ("rest", "휴식 권유"),
        ("away", "자리비움"),
        ("warning", "경고·잔소리"),
        ("leave", "퇴근 권유"),
        ("stats", "통계 화면"),
        ("settings", "설정 화면"),
        ("alert", "알림창"),
        ("profile", "프로필"),
    )

    ROLE_TO_SETTING = {
        "default": "default", "playful": "default",
        "cheer": "cheer", "cute_cheer": "cheer",
        "rest": "rest", "away": "away",
        "worry": "warning", "nag": "warning",
        "praise": "leave", "stats": "stats",
        "settings": "settings", "alert": "alert",
        "master_face": "profile",
    }

    def __init__(self):
        self._drag_origin = None
        self._hotkey_stop = threading.Event()
        self._hotkey_thread = None
        self._image_cache = {}
        self._presentation_suppressed = False
        super().__init__()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.preferences.always_on_top)
        self.root.bind("<Escape>", self._emergency_hide)
        self._enable_detail_drag_surfaces()
        self._restore_window_position()
        self._start_global_hotkey()
        self._check_font_available()
        self.root.after(1500, self._sync_presentation_state)

    def _check_font_available(self):
        try:
            if self.FONT_FAMILY not in tkfont.families(self.root):
                core.log.warning("Pretendard not installed; Tk will use a system fallback font")
        except tk.TclError:
            core.log.warning("font availability check failed")

    @staticmethod
    def _monitor_work_areas():
        if os.name != "nt":
            return []
        user32 = ctypes.windll.user32
        areas = []

        class MONITORINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.DWORD),
                ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD),
            ]

        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            ctypes.c_ssize_t,
        )

        @callback_type
        def enum_proc(hmonitor, _hdc, _rect, _data):
            info = MONITORINFO()
            info.cbSize = ctypes.sizeof(MONITORINFO)
            if user32.GetMonitorInfoW(hmonitor, ctypes.byref(info)):
                r = info.rcWork
                areas.append((int(r.left), int(r.top), int(r.right), int(r.bottom)))
            return True

        try:
            user32.EnumDisplayMonitors(None, None, enum_proc, 0)
        except Exception:
            core.log.exception("monitor enumeration failed")
        return areas

    def _work_areas(self):
        areas = self._monitor_work_areas()
        if areas:
            return areas
        return [(0, 0, self.root.winfo_screenwidth(), self.root.winfo_screenheight())]

    def _best_work_area(self, x, y, width, height):
        areas = self._work_areas()
        rect = (x, y, x + width, y + height)
        scored = [(_intersection_area(rect, area), area) for area in areas]
        best_score, best = max(scored, key=lambda item: item[0])
        if best_score:
            return best
        cx = x + width / 2
        cy = y + height / 2
        return min(
            areas,
            key=lambda area: (
                cx - (area[0] + area[2]) / 2
            ) ** 2 + (
                cy - (area[1] + area[3]) / 2
            ) ** 2,
        )

    def _native_toplevel_handle(self):
        """Return Tk's real wrapper HWND, not the embedded client child HWND."""
        client = int(self.root.winfo_id())
        if os.name != "nt":
            return client
        try:
            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            wrapper = user32.GetAncestor(client, GA_ROOT)
            return int(wrapper or client)
        except Exception:
            core.log.exception("native top-level handle lookup failed")
            return client

    def _set_window_rect(self, x, y, width, height):
        self.root.geometry(f"{max(1, int(width))}x{max(1, int(height))}")
        self.root.update_idletasks()
        if os.name == "nt":
            try:
                ctypes.windll.user32.SetWindowPos(
                    self._native_toplevel_handle(),
                    0,
                    int(x),
                    int(y),
                    int(width),
                    int(height),
                    SWP_NOZORDER | SWP_NOACTIVATE,
                )
                return
            except Exception:
                core.log.exception("SetWindowPos failed")
        self.root.geometry(f"{int(width)}x{int(height)}+{max(0, int(x))}+{max(0, int(y))}")

    def _clamp_rect(self, x, y, width, height):
        area = self._best_work_area(x, y, width, height)
        aw = max(1, area[2] - area[0])
        ah = max(1, area[3] - area[1])
        width = min(width, max(260, aw - 12))
        height = min(height, max(260, ah - 12))
        x = min(max(x, area[0]), area[2] - width)
        y = min(max(y, area[1]), area[3] - height)
        return int(x), int(y), int(width), int(height)

    def _effective_widget_scale(self) -> int:
        var = getattr(self, "widget_scale_var", None)
        if var is not None:
            try:
                return int(var.get())
            except (tk.TclError, ValueError, TypeError):
                pass
        return self.preferences.widget_scale

    def _scale(self, value: int | float) -> int:
        return max(1, round(float(value) * self._effective_widget_scale() / 100.0))

    def _timer_size(self):
        return self._scale(self.COMPACT_SIZE[0]), self._scale(self.COMPACT_SIZE[1])

    def _resize_for_page(self, name: str):
        if name == "timer":
            width, height = self._timer_size()
        elif name == "settings":
            width, height = self.SETTINGS_SIZE
        else:
            width, height = self.DETAIL_SIZE

        try:
            x, y = self.root.winfo_x(), self.root.winfo_y()
        except tk.TclError:
            x, y = 0, 0
        x, y, width, height = self._clamp_rect(x, y, width, height)
        self.root.minsize(width, height)
        self._set_window_rect(x, y, width, height)

    def _restore_window_position(self):
        self.root.update_idletasks()
        width = max(1, self.root.winfo_width())
        height = max(1, self.root.winfo_height())
        if not (self.preferences.window_x == -1 and self.preferences.window_y == -1):
            x, y = self.preferences.window_x, self.preferences.window_y
        else:
            area = self._work_areas()[0]
            x = area[2] - width - 24
            y = area[1] + 48
        x, y, width, height = self._clamp_rect(x, y, width, height)
        self._set_window_rect(x, y, width, height)

    def _save_window_position(self):
        try:
            updated = replace(
                self.preferences,
                window_x=int(self.root.winfo_x()),
                window_y=int(self.root.winfo_y()),
            )
            save_user_settings(core.SETTINGS_FILE, updated)
            self.preferences = updated
        except Exception:
            core.log.exception("window position save failed")

    def _enable_detail_drag_surfaces(self):
        for page in (self.stats_page, self.settings_page):
            children = page.winfo_children()
            if not children:
                continue
            header = children[0]
            self._bind_drag_surface(header)
            for child in header.winfo_children():
                if isinstance(child, tk.Label):
                    self._bind_drag_surface(child)

    def _label(self, parent, text="", size=10, weight="normal", fg=core.TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=(self.FONT_FAMILY, size, "normal"),
            fg=fg,
            bg=bg or parent.cget("bg"),
            **kwargs,
        )

    def _button(self, parent, text, command, primary=False, width=None):
        button = super()._button(parent, text, command, primary=primary, width=width)
        button.configure(font=(self.FONT_FAMILY, 9, "normal"))
        return button

    @staticmethod
    def _clean_character_alpha(image):
        return threshold_alpha(image)

    def _start_drag(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_window(self, event):
        if not self._drag_origin:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        x = win_x + event.x_root - start_x
        y = win_y + event.y_root - start_y
        self._set_window_rect(x, y, self.root.winfo_width(), self.root.winfo_height())

    def _stop_drag(self, _event=None):
        self._drag_origin = None
        try:
            x, y, width, height = self._clamp_rect(
                self.root.winfo_x(),
                self.root.winfo_y(),
                self.root.winfo_width(),
                self.root.winfo_height(),
            )
            self._set_window_rect(x, y, width, height)
            self._save_window_position()
        except Exception:
            core.log.exception("drag completion failed")

    def _bind_drag_surface(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag_window)
        widget.bind("<ButtonRelease-1>", self._stop_drag)

    def _emergency_hide(self, _event=None):
        self.root.attributes("-topmost", False)
        self.root.withdraw()

    def _toggle_hidden(self):
        try:
            if self.root.state() == "withdrawn" or not self.root.winfo_viewable():
                self.show()
            else:
                self._emergency_hide()
        except tk.TclError:
            return

    def _start_global_hotkey(self):
        if os.name != "nt" or self._hotkey_thread is not None:
            return

        def hotkey_loop():
            user32 = ctypes.windll.user32
            msg = wintypes.MSG()
            registered = False
            try:
                user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE)
                registered = bool(
                    user32.RegisterHotKey(
                        None,
                        GLOBAL_HOTKEY_ID,
                        MOD_CONTROL | MOD_SHIFT,
                        VK_H,
                    )
                )
                if not registered:
                    core.log.warning("global hotkey Ctrl+Shift+H could not be registered")
                    return
                while not self._hotkey_stop.wait(0.05):
                    while user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, PM_REMOVE):
                        if msg.message == WM_HOTKEY and int(msg.wParam) == GLOBAL_HOTKEY_ID:
                            self._tray_call(self._toggle_hidden)
            except Exception:
                core.log.exception("global hotkey loop failed")
            finally:
                if registered:
                    try:
                        user32.UnregisterHotKey(None, GLOBAL_HOTKEY_ID)
                    except Exception:
                        pass

        self._hotkey_thread = threading.Thread(target=hotkey_loop, daemon=True, name="KyungheeHotkey")
        self._hotkey_thread.start()

    def _stored_image_path(self, value: str):
        if not value:
            return None
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = USER_IMAGE_DIR / path
        return path

    def _custom_image(self, role: str):
        key = self.ROLE_TO_SETTING.get(role, "default")
        value = getattr(self.preferences, f"image_{key}", "")
        path = self._stored_image_path(value)
        mode = getattr(self.preferences, f"image_{key}_mode", "fit")
        if path and not path.is_file():
            core.log.warning("custom image missing for %s: %s", key, path)
            return None, mode
        return path, mode

    def _load_character_image(self, role: str, max_size=(470, 300), preserve_alpha=False):
        custom, mode = self._custom_image(role)
        path = custom or resolve_asset(role)
        if not path:
            return super()._load_character_image(role, max_size, preserve_alpha)
        try:
            stat_key = path.stat().st_mtime_ns
        except OSError:
            stat_key = 0
        cache_key = (str(path), stat_key, tuple(max_size), mode, bool(preserve_alpha))
        cached = self._image_cache.get(cache_key)
        if cached is not None:
            return cached.copy()
        with Image.open(path) as src:
            if src.width > MAX_CUSTOM_IMAGE_DIMENSION or src.height > MAX_CUSTOM_IMAGE_DIMENSION:
                raise ValueError(f"이미지가 너무 큽니다. 최대 {MAX_CUSTOM_IMAGE_DIMENSION}px까지 사용할 수 있습니다.")
            image = resize_rgba_alpha_safe(
                src,
                max_size,
                crop=bool(mode == "crop" and custom),
                centering=(0.5, 0.5),
            )
            if preserve_alpha:
                result = image
            else:
                canvas = Image.new("RGBA", image.size, core.PANEL)
                canvas.alpha_composite(image)
                result = canvas.convert("RGB")
        self._image_cache[cache_key] = result.copy()
        return result

    def _set_small_avatar(self, target):
        try:
            image = self._load_character_image("master_face", (26, 26), preserve_alpha=False)
            image.thumbnail((26, 26), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (26, 26), core.BG)
            canvas.paste(image, ((26 - image.width) // 2, (26 - image.height) // 2))
            photo = ImageTk.PhotoImage(canvas)
            target.image = photo
            target.configure(image=photo)
        except Exception:
            core.log.exception("avatar asset failed")

    def apply_preferences(self, preferences) -> None:
        self._image_cache.clear()
        super().apply_preferences(preferences)
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character("default")
        self._resize_for_page(self.current_page)

    def _sync_presentation_state(self):
        try:
            suppressed = should_suppress_overlay_notifications()
            if suppressed != self._presentation_suppressed:
                self._presentation_suppressed = suppressed
                core.log.info("presentation/fullscreen suppression=%s", suppressed)
            if suppressed:
                self.root.attributes("-topmost", False)
                self._destroy_toast()
            elif self.root.winfo_viewable():
                self.root.attributes("-topmost", self.preferences.always_on_top)
        except Exception:
            core.log.exception("presentation state sync failed")
        finally:
            if self.root.winfo_exists():
                self.root.after(2000, self._sync_presentation_state)

    def show(self):
        self.root.deiconify()
        self.root.update_idletasks()
        x, y, width, height = self._clamp_rect(
            self.root.winfo_x(),
            self.root.winfo_y(),
            self.root.winfo_width(),
            self.root.winfo_height(),
        )
        self._set_window_rect(x, y, width, height)
        self.root.lift()
        self.root.attributes(
            "-topmost",
            self.preferences.always_on_top and not should_suppress_overlay_notifications(),
        )

    def show_toast(self, text):
        if should_suppress_overlay_notifications():
            core.log.info("toast suppressed during fullscreen/presentation state")
            return
        super().show_toast(text)

    def show_break_toast(self, text, allow_snooze=True):
        if should_suppress_overlay_notifications():
            core.log.info("break toast suppressed during fullscreen/presentation state")
            return
        super().show_break_toast(text, allow_snooze=allow_snooze)

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            max_size = (self._scale(self.CHARACTER_MAX[0]), self._scale(self.CHARACTER_MAX[1]))
            image = self._load_character_image(role, max_size, preserve_alpha=True)
            image = self._clean_character_alpha(image)
            self.character_photo = ImageTk.PhotoImage(image)
            self.character.configure(image=self.character_photo)
            self.character_role = role
        except Exception:
            core.log.exception("character asset failed: %s", role)

    def _build_timer_page(self):
        page = self.timer_page
        page.configure(bg=self.TRANSPARENT_KEY)
        hero = tk.Frame(page, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        hero.pack(fill="both", expand=True)
        self.hero = hero

        # Always keep a small invisible drag surface, even when time/status are hidden.
        self.drag_strip = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        self.drag_strip.place(x=0, y=0, relwidth=1.0, height=18)
        self._bind_drag_surface(self.drag_strip)

        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor="s")

        p = self.preferences
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        self.clock = clock
        clock.place(x=self._scale(6), y=self._scale(6))
        self.cont = OutlinedText(
            clock, "00:00:00", family=self.FONT_FAMILY, size=self._scale(p.time_text_size),
            fg=p.time_text_color, outline=_outline_for(p.time_text_color),
            bg=self.TRANSPARENT_KEY, cursor="fleur",
        )
        self.cont.pack(anchor="w")
        self.main_status = OutlinedText(
            clock, "집중 중", family=self.FONT_FAMILY, size=self._scale(p.status_text_size),
            fg=p.status_text_color, outline=_outline_for(p.status_text_color),
            bg=self.TRANSPARENT_KEY, cursor="fleur",
        )
        self.main_status.pack(anchor="w", pady=(0, 1))
        for widget in (clock, self.cont, self.main_status):
            self._bind_drag_surface(widget)

        self.escape_control = tk.Label(
            hero, text="×", font=(self.FONT_FAMILY, self._scale(12), "normal"),
            fg=self.ESCAPE_TEXT, bg=self.TRANSPARENT_KEY, bd=0,
            highlightthickness=0, cursor="hand2",
        )
        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")
        self.escape_control.bind("<Button-1>", self._emergency_hide)

        self.speech = OutlinedText(
            hero, pick("playful"), family=self.FONT_FAMILY, size=self._scale(p.message_text_size),
            fg=p.message_text_color, outline=_outline_for(p.message_text_color),
            bg=self.TRANSPARENT_KEY, wraplength=self._scale(self.BUBBLE_WRAP),
            justify="center", cursor="hand2",
        )
        self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)
        self._apply_widget_appearance()

    def _effective_display_flag(self, key: str) -> bool:
        vars_map = getattr(self, "display_bool_vars", None)
        if vars_map and key in vars_map:
            try:
                return bool(vars_map[key].get())
            except tk.TclError:
                pass
        return bool(getattr(self.preferences, key))

    def _preview_widget_controls(self, _value=None):
        if not hasattr(self, "cont"):
            return
        self._image_cache.clear()
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character("default")
        # Keep the settings panel usable while previewing. The timer window size
        # is recalculated when the user returns to the timer page.
        if self.current_page == "timer":
            self._resize_for_page("timer")

    def _apply_widget_appearance(self):
        if not hasattr(self, "cont"):
            return
        p = self.preferences
        self.cont.set_style(
            size=self._scale(p.time_text_size), fg=p.time_text_color,
            outline=_outline_for(p.time_text_color),
        )
        self.main_status.set_style(
            size=self._scale(p.status_text_size), fg=p.status_text_color,
            outline=_outline_for(p.status_text_color),
        )
        self.speech.set_style(
            size=self._scale(p.message_text_size), fg=p.message_text_color,
            outline=_outline_for(p.message_text_color),
        )

        if self._effective_display_flag("show_time"):
            if not self.cont.winfo_manager():
                self.cont.pack(anchor="w")
        else:
            self.cont.pack_forget()
        if self._effective_display_flag("show_status"):
            if not self.main_status.winfo_manager():
                self.main_status.pack(anchor="w", pady=(0, 1))
        else:
            self.main_status.pack_forget()
        if self._effective_display_flag("show_message"):
            self.speech.place(relx=0.5, rely=1.0, y=-self._scale(3), anchor="s")
        else:
            self.speech.place_forget()

        self.clock.place(x=self._scale(6), y=self._scale(6))
        self.character.place(relx=0.5, rely=1.0, y=-self._scale(18), anchor="s")
        self.escape_control.configure(font=(self.FONT_FAMILY, self._scale(12), "normal"))
        self.escape_control.place(relx=1.0, x=-self._scale(8), y=self._scale(5), anchor="ne")

    def _choose_color(self, key):
        var = self.style_color_vars[key]
        picked = colorchooser.askcolor(color=var.get(), parent=self.root)[1]
        if picked:
            var.set(picked.upper())
            self.color_swatches[key].configure(bg=picked)

    def _choose_image(self, key):
        path = filedialog.askopenfilename(
            parent=self.root,
            title=f"{dict(self.IMAGE_ROWS)[key]} 이미지 선택",
            filetypes=[("이미지", "*.png *.jpg *.jpeg *.webp"), ("모든 파일", "*.*")],
        )
        if not path:
            return

        source = Path(path)
        try:
            with Image.open(source) as probe:
                if probe.width > MAX_CUSTOM_IMAGE_DIMENSION or probe.height > MAX_CUSTOM_IMAGE_DIMENSION:
                    raise ValueError(
                        f"이미지가 너무 큽니다. 가로·세로 각각 {MAX_CUSTOM_IMAGE_DIMENSION}px 이하를 사용해 주세요."
                    )
                probe.verify()
            USER_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
            for old in USER_IMAGE_DIR.glob(f"{key}.*"):
                try:
                    old.unlink()
                except OSError:
                    core.log.warning("old custom image could not be removed: %s", old)
            suffix = source.suffix.lower()
            if suffix not in {".png", ".jpg", ".jpeg", ".webp"}:
                raise ValueError("PNG, JPG, JPEG, WebP 이미지만 사용할 수 있습니다.")
            destination = USER_IMAGE_DIR / f"{key}{suffix}"
            shutil.copy2(source, destination)
            self.image_path_vars[key].set(destination.name)
            self.image_name_vars[key].set(destination.name)
            self._image_cache.clear()
        except Exception as exc:
            core.log.exception("custom image import failed: %s", source)
            self.settings_status.configure(text=f"이미지 선택 실패: {exc}", fg=core.AMBER)

    def _reset_image(self, key):
        self.image_path_vars[key].set("")
        self.image_name_vars[key].set("기본 이미지")
        self.image_mode_vars[key].set("자동 맞춤")
        self._image_cache.clear()
        if USER_IMAGE_DIR.is_dir():
            for old in USER_IMAGE_DIR.glob(f"{key}.*"):
                try:
                    old.unlink()
                except OSError:
                    core.log.warning("custom image reset could not remove: %s", old)

    def _image_display_name(self, value):
        if not value:
            return "기본 이미지"
        path = self._stored_image_path(value)
        if path and path.is_file():
            return path.name
        return f"⚠ 파일 없음: {Path(value).name}"

    def _build_settings_page(self):
        page = self.settings_page
        self._build_header(page, "설정", back_command=lambda: self._show_page("timer"))

        outer = tk.Frame(page, bg=core.BG)
        outer.pack(fill="both", expand=True, padx=7, pady=(2, 7))
        canvas = tk.Canvas(outer, bg=core.PANEL, highlightthickness=0, bd=0)
        scroll = tk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        content = tk.Frame(canvas, bg=core.PANEL)
        window_id = canvas.create_window((0, 0), window=content, anchor="nw")
        content.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window_id, width=e.width))

        p = self.preferences
        pad = {"padx": 14}
        self._label(content, "앱 설정", size=11, bg=core.PANEL).pack(anchor="w", pady=(12, 5), **pad)
        self.settings_bool_vars = {
            "start_with_windows": tk.BooleanVar(value=p.start_with_windows),
            "always_on_top": tk.BooleanVar(value=p.always_on_top),
            "break_reminders": tk.BooleanVar(value=p.break_reminders),
            "workday_reminders": tk.BooleanVar(value=p.workday_reminders),
        }
        for key, caption in (
            ("start_with_windows", "Windows 시작 시 자동 실행"),
            ("always_on_top", "메인 창 항상 위 표시"),
            ("break_reminders", "휴식 알림 사용"),
            ("workday_reminders", "퇴근 시간 알림 사용"),
        ):
            tk.Checkbutton(
                content, text=caption, variable=self.settings_bool_vars[key],
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL,
                activeforeground=core.TEXT, activebackground=core.PANEL,
                selectcolor=core.PANEL_2, highlightthickness=0, bd=0, cursor="hand2",
            ).pack(anchor="w", pady=1, **pad)

        self._label(content, "긴급 숨기기 단축키: Ctrl+Shift+H", size=8, fg=core.MUTED, bg=core.PANEL).pack(
            anchor="w", pady=(2, 2), **pad
        )

        self._label(content, "위젯 표시", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)
        scale_row = tk.Frame(content, bg=core.PANEL)
        scale_row.pack(fill="x", pady=(0, 5), **pad)
        self._label(scale_row, "전체 크기", size=9, bg=core.PANEL).pack(side="left")
        self.widget_scale_var = tk.IntVar(value=p.widget_scale)
        self.widget_scale_value = self._label(scale_row, f"{p.widget_scale}%", size=9, fg=core.MUTED, bg=core.PANEL)
        self.widget_scale_value.pack(side="right")
        scale = tk.Scale(
            content, from_=80, to=140, orient="horizontal", resolution=5,
            variable=self.widget_scale_var, showvalue=False, length=360,
            fg=core.TEXT, bg=core.PANEL, troughcolor=core.PANEL_2,
            highlightthickness=0, bd=0,
            command=lambda value: (
                self.widget_scale_value.configure(text=f"{int(float(value))}%"),
                self._preview_widget_controls(value),
            ),
        )
        scale.pack(anchor="w", pady=(0, 4), **pad)
        self.display_bool_vars = {
            "show_time": tk.BooleanVar(value=p.show_time),
            "show_status": tk.BooleanVar(value=p.show_status),
            "show_message": tk.BooleanVar(value=p.show_message),
        }
        for key, caption in (
            ("show_time", "시간 표시"),
            ("show_status", "상태 표시"),
            ("show_message", "메시지 표시"),
        ):
            tk.Checkbutton(
                content, text=caption, variable=self.display_bool_vars[key],
                command=self._preview_widget_controls,
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL,
                activeforeground=core.TEXT, activebackground=core.PANEL,
                selectcolor=core.PANEL_2, highlightthickness=0, bd=0, cursor="hand2",
            ).pack(anchor="w", pady=1, **pad)
        self._label(
            content,
            "시간과 상태를 모두 꺼도 위쪽 투명 드래그 영역으로 창을 이동할 수 있습니다.",
            size=8, fg=core.MUTED, bg=core.PANEL,
        ).pack(anchor="w", pady=(2, 4), **pad)

        self._label(content, "위젯 글자", size=11, bg=core.PANEL).pack(anchor="w", pady=(14, 4), **pad)
        self._label(
            content,
            "Pretendard Regular 고정 · 외곽선 색은 선택한 글자색에 맞춰 자동 조정됩니다.",
            size=8, fg=core.MUTED, bg=core.PANEL,
        ).pack(anchor="w", pady=(0, 5), **pad)

        self.style_size_vars = {
            "time": tk.StringVar(value=str(p.time_text_size)),
            "status": tk.StringVar(value=str(p.status_text_size)),
            "message": tk.StringVar(value=str(p.message_text_size)),
        }
        self.style_color_vars = {
            "time": tk.StringVar(value=p.time_text_color),
            "status": tk.StringVar(value=p.status_text_color),
            "message": tk.StringVar(value=p.message_text_color),
        }
        self.color_swatches = {}
        ranges = {"time": "14~24", "status": "7~12", "message": "9~16"}
        labels = {"time": "시간", "status": "상태", "message": "메시지"}
        for key in ("time", "status", "message"):
            row = tk.Frame(content, bg=core.PANEL)
            row.pack(fill="x", pady=2, **pad)
            self._label(row, labels[key], size=9, bg=core.PANEL).pack(side="left")
            self._label(row, ranges[key], size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left", padx=(8, 4))
            tk.Entry(
                row, textvariable=self.style_size_vars[key], width=4, justify="center",
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL_2,
                insertbackground=core.TEXT, relief="flat", bd=0,
            ).pack(side="left", padx=(4, 10), ipady=2)
            swatch = tk.Label(row, width=2, bg=self.style_color_vars[key].get(), bd=0)
            swatch.pack(side="left", padx=(0, 5), ipady=5)
            self.color_swatches[key] = swatch
            tk.Entry(
                row, textvariable=self.style_color_vars[key], width=9,
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL_2,
                insertbackground=core.TEXT, relief="flat", bd=0,
            ).pack(side="left", ipady=2)
            self._button(row, "색상 선택", lambda k=key: self._choose_color(k)).pack(side="left", padx=(6, 0))

        self._label(content, "상황별 경희 이미지", size=11, bg=core.PANEL).pack(anchor="w", pady=(16, 4), **pad)
        self._label(
            content,
            "권장: 투명 PNG, 세로형 900×1200 이상(최소 600×800). 인물 주변 여백 5~10%. 프로필은 512×512 이상 권장.",
            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",
        ).pack(anchor="w", pady=(0, 3), **pad)
        self._label(
            content,
            "선택한 이미지는 앱 전용 폴더로 복사됩니다. 자동 맞춤 = 전체 표시 / 가운데 크롭 = 중앙 기준 자르기",
            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",
        ).pack(anchor="w", pady=(0, 7), **pad)

        self.image_path_vars = {}
        self.image_name_vars = {}
        self.image_mode_vars = {}
        for key, caption in self.IMAGE_ROWS:
            path_value = getattr(p, f"image_{key}")
            mode_value = getattr(p, f"image_{key}_mode")
            self.image_path_vars[key] = tk.StringVar(value=path_value)
            self.image_name_vars[key] = tk.StringVar(value=self._image_display_name(path_value))
            self.image_mode_vars[key] = tk.StringVar(value="가운데 크롭" if mode_value == "crop" else "자동 맞춤")

            row = tk.Frame(content, bg=core.PANEL)
            row.pack(fill="x", pady=2, **pad)
            self._label(row, caption, size=9, bg=core.PANEL).pack(side="left")
            name_label = tk.Label(
                row, textvariable=self.image_name_vars[key], width=22, anchor="w",
                font=(self.FONT_FAMILY, 8, "normal"), fg=core.MUTED, bg=core.PANEL,
            )
            name_label.pack(side="left", padx=(10, 5))
            tk.OptionMenu(row, self.image_mode_vars[key], "자동 맞춤", "가운데 크롭").pack(side="left", padx=4)
            self._button(row, "선택", lambda k=key: self._choose_image(k)).pack(side="left", padx=4)
            self._button(row, "기본값", lambda k=key: self._reset_image(k)).pack(side="left")

        self._label(content, "퇴근 시간", size=11, bg=core.PANEL).pack(anchor="w", pady=(16, 4), **pad)
        self.settings_time_vars = {
            "wind_down": tk.StringVar(value=p.wind_down),
            "leave_mode": tk.StringVar(value=p.leave_mode),
            "strong_leave": tk.StringVar(value=p.strong_leave),
            "late_leave": tk.StringVar(value=p.late_leave),
        }
        for key, caption in (
            ("wind_down", "마무리 예고"),
            ("leave_mode", "퇴근 모드 시작"),
            ("strong_leave", "적극 퇴근 권고"),
            ("late_leave", "야근 잔소리 시작"),
        ):
            row = tk.Frame(content, bg=core.PANEL)
            row.pack(fill="x", pady=2, **pad)
            self._label(row, caption, size=9, bg=core.PANEL).pack(side="left")
            tk.Entry(
                row, textvariable=self.settings_time_vars[key], width=7, justify="center",
                font=(self.FONT_FAMILY, 9, "normal"), fg=core.TEXT, bg=core.PANEL_2,
                insertbackground=core.TEXT, relief="flat", bd=0,
            ).pack(side="right", ipady=2)

        save_row = tk.Frame(content, bg=core.PANEL)
        save_row.pack(fill="x", padx=14, pady=(16, 16))
        self.settings_status = self._label(save_row, "", size=9, fg=core.GREEN, bg=core.PANEL)
        self.settings_status.pack(side="left")
        self._button(save_row, "설정 저장", self._save_settings, primary=True).pack(side="right")

    def _show_page(self, name: str):
        super()._show_page(name)
        if name == "timer":
            self._preview_widget_controls()
            self._resize_for_page("timer")

    def _save_settings(self):
        try:
            candidate = UserSettings(
                start_with_windows=self.settings_bool_vars["start_with_windows"].get(),
                always_on_top=self.settings_bool_vars["always_on_top"].get(),
                break_reminders=self.settings_bool_vars["break_reminders"].get(),
                workday_reminders=self.settings_bool_vars["workday_reminders"].get(),
                wind_down=self.settings_time_vars["wind_down"].get().strip(),
                leave_mode=self.settings_time_vars["leave_mode"].get().strip(),
                strong_leave=self.settings_time_vars["strong_leave"].get().strip(),
                late_leave=self.settings_time_vars["late_leave"].get().strip(),
                window_x=self.preferences.window_x,
                window_y=self.preferences.window_y,
                widget_scale=int(self.widget_scale_var.get()),
                show_time=self.display_bool_vars["show_time"].get(),
                show_status=self.display_bool_vars["show_status"].get(),
                show_message=self.display_bool_vars["show_message"].get(),
                time_text_size=int(self.style_size_vars["time"].get()),
                status_text_size=int(self.style_size_vars["status"].get()),
                message_text_size=int(self.style_size_vars["message"].get()),
                time_text_color=validate_hex_color(self.style_color_vars["time"].get()),
                status_text_color=validate_hex_color(self.style_color_vars["status"].get()),
                message_text_color=validate_hex_color(self.style_color_vars["message"].get()),
                **{f"image_{k}": self.image_path_vars[k].get() for k, _ in self.IMAGE_ROWS},
                **{
                    f"image_{k}_mode": "crop" if self.image_mode_vars[k].get() == "가운데 크롭" else "fit"
                    for k, _ in self.IMAGE_ROWS
                },
            )
            candidate.workday_policy()
            candidate.validate_widget_style()
            previous = self.preferences
            startup_changed = candidate.start_with_windows != previous.start_with_windows
            if startup_changed:
                set_windows_startup(candidate.start_with_windows)
            try:
                self.apply_preferences(candidate)
            except Exception:
                if startup_changed:
                    set_windows_startup(previous.start_with_windows)
                raise
        except Exception as exc:
            core.log.exception("settings save failed")
            self.settings_status.configure(text=str(exc), fg=core.AMBER)
            return

        self.last_work_mode = self._current_workday_state().mode
        self.settings_status.configure(text="저장됨 · 메인 화면에 즉시 반영", fg=core.GREEN)

    def _update_ui(self):
        super()._update_ui()
        away = self.state.session.is_away
        status_color = core.AMBER if away else self.preferences.status_text_color
        self.main_status.configure(
            text="자리비움 중" if away else "집중 중",
            fg=status_color,
            outline=_outline_for(status_color),
        )

    def quit(self):
        self._hotkey_stop.set()
        try:
            self._save_window_position()
        except Exception:
            pass
        super().quit()


if __name__ == "__main__":
    if os.name != "nt":
        raise SystemExit("Windows only")
    enable_per_monitor_dpi_awareness()
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
