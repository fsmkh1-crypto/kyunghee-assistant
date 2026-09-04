from __future__ import annotations

from pathlib import Path
import tkinter as tk
from tkinter import colorchooser, filedialog
import tkinter.font as tkfont
from PIL import Image, ImageOps, ImageTk

import app as core
from app import SingleInstance
from asset_manager import resolve_asset
from desktop_app import DesktopApp
from messages import pick
from settings import UserSettings, set_windows_startup, validate_hex_color


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
        self._draw_items()
        self._refresh_geometry()

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

    def _refresh_geometry(self):
        self.update_idletasks()
        bbox = self.bbox("all")
        if not bbox:
            tk.Canvas.configure(self, width=1, height=1)
            return
        width = self._wraplength + 8 if self._wraplength else max(1, bbox[2] - bbox[0] + 6)
        height = max(1, bbox[3] - bbox[1] + 6)
        tk.Canvas.configure(self, width=width, height=height)

    def set_style(self, *, size=None, fg=None, outline=None):
        if size is not None:
            self._font.configure(size=int(size), weight="normal")
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
        self._refresh_geometry()

    def configure(self, cnf=None, **kwargs):
        if cnf:
            kwargs.update(cnf)
        text = kwargs.pop("text", None)
        fg = kwargs.pop("fg", kwargs.pop("foreground", None))
        outline = kwargs.pop("outline", None)
        if text is not None:
            self._text = str(text)
            for item in self._outline_items:
                self.itemconfigure(item, text=self._text)
            self.itemconfigure(self._main_item, text=self._text)
        if fg is not None or outline is not None:
            self.set_style(fg=fg, outline=outline)
        if kwargs:
            tk.Canvas.configure(self, **kwargs)
        if text is not None:
            self._refresh_geometry()

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
        super().__init__()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", self.preferences.always_on_top)
        self.root.bind("<Escape>", self._emergency_hide)
        self._drag_origin = None

    def _resize_for_page(self, name: str):
        if name == "timer":
            width, height = self.COMPACT_SIZE
        elif name == "settings":
            width, height = self.SETTINGS_SIZE
        else:
            width, height = self.DETAIL_SIZE
        self.root.minsize(width, height)
        self.root.geometry(f"{width}x{height}")

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
        rgba = image.convert("RGBA")
        alpha = rgba.getchannel("A")
        rgba.putalpha(alpha.point(lambda value: 0 if value < 72 else 255))
        return rgba

    def _start_drag(self, event):
        self._drag_origin = (event.x_root, event.y_root, self.root.winfo_x(), self.root.winfo_y())

    def _drag_window(self, event):
        if not self._drag_origin:
            return
        start_x, start_y, win_x, win_y = self._drag_origin
        self.root.geometry(f"+{win_x + event.x_root - start_x}+{win_y + event.y_root - start_y}")

    def _stop_drag(self, _event=None):
        self._drag_origin = None

    def _bind_drag_surface(self, widget):
        widget.bind("<ButtonPress-1>", self._start_drag)
        widget.bind("<B1-Motion>", self._drag_window)
        widget.bind("<ButtonRelease-1>", self._stop_drag)

    def _emergency_hide(self, _event=None):
        self.root.attributes("-topmost", False)
        self.root.withdraw()

    def _custom_image(self, role: str):
        key = self.ROLE_TO_SETTING.get(role, "default")
        value = getattr(self.preferences, f"image_{key}", "")
        path = Path(value).expanduser() if value else None
        mode = getattr(self.preferences, f"image_{key}_mode", "fit")
        return (path if path and path.is_file() else None), mode

    def _load_character_image(self, role: str, max_size=(470, 300), preserve_alpha=False):
        custom, mode = self._custom_image(role)
        path = custom or resolve_asset(role)
        if not path:
            return super()._load_character_image(role, max_size, preserve_alpha)
        with Image.open(path) as src:
            image = src.convert("RGBA")
            if mode == "crop" and custom:
                image = ImageOps.fit(image, max_size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.5))
            else:
                image.thumbnail(max_size, Image.Resampling.LANCZOS)
            if preserve_alpha:
                return image
            canvas = Image.new("RGBA", image.size, core.PANEL)
            canvas.alpha_composite(image)
            return canvas.convert("RGB")

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
        super().apply_preferences(preferences)
        self._apply_widget_appearance()
        self.character_role = None
        self._set_character(self.ROLE_TO_SETTING.get("default", "default"))

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", self.preferences.always_on_top)

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            image = self._load_character_image(role, self.CHARACTER_MAX, preserve_alpha=True)
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

        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-18, anchor="s")

        p = self.preferences
        clock = tk.Frame(hero, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0, cursor="fleur")
        clock.place(x=6, y=6)
        self.cont = OutlinedText(
            clock, "00:00:00", family=self.FONT_FAMILY, size=p.time_text_size,
            fg=p.time_text_color, outline=_outline_for(p.time_text_color),
            bg=self.TRANSPARENT_KEY, cursor="fleur",
        )
        self.cont.pack(anchor="w")
        self.main_status = OutlinedText(
            clock, "집중 중", family=self.FONT_FAMILY, size=p.status_text_size,
            fg=p.status_text_color, outline=_outline_for(p.status_text_color),
            bg=self.TRANSPARENT_KEY, cursor="fleur",
        )
        self.main_status.pack(anchor="w", pady=(0, 1))
        for widget in (clock, self.cont, self.main_status):
            self._bind_drag_surface(widget)

        self.escape_control = tk.Label(
            hero, text="×", font=(self.FONT_FAMILY, 12, "normal"),
            fg=self.ESCAPE_TEXT, bg=self.TRANSPARENT_KEY, bd=0,
            highlightthickness=0, cursor="hand2",
        )
        self.escape_control.place(relx=1.0, x=-8, y=5, anchor="ne")
        self.escape_control.bind("<Button-1>", self._emergency_hide)

        self.speech = OutlinedText(
            hero, pick("playful"), family=self.FONT_FAMILY, size=p.message_text_size,
            fg=p.message_text_color, outline=_outline_for(p.message_text_color),
            bg=self.TRANSPARENT_KEY, wraplength=self.BUBBLE_WRAP,
            justify="center", cursor="hand2",
        )
        self.speech.place(relx=0.5, rely=1.0, y=-3, anchor="s")

        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        self.speech.bind("<Button-1>", self._cycle_message)

    def _apply_widget_appearance(self):
        if not hasattr(self, "cont"):
            return
        p = self.preferences
        self.cont.set_style(
            size=p.time_text_size, fg=p.time_text_color,
            outline=_outline_for(p.time_text_color),
        )
        self.main_status.set_style(
            size=p.status_text_size, fg=p.status_text_color,
            outline=_outline_for(p.status_text_color),
        )
        self.speech.set_style(
            size=p.message_text_size, fg=p.message_text_color,
            outline=_outline_for(p.message_text_color),
        )

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
        if path:
            self.image_path_vars[key].set(path)
            self.image_name_vars[key].set(Path(path).name)

    def _reset_image(self, key):
        self.image_path_vars[key].set("")
        self.image_name_vars[key].set("기본 이미지")
        self.image_mode_vars[key].set("자동 맞춤")

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
            "자동 맞춤 = 전체 이미지를 비율 유지해 표시 / 가운데 크롭 = 화면 비율에 맞춰 중앙 기준으로 잘라 표시",
            size=8, fg=core.MUTED, bg=core.PANEL, wraplength=590, justify="left",
        ).pack(anchor="w", pady=(0, 7), **pad)

        self.image_path_vars = {}
        self.image_name_vars = {}
        self.image_mode_vars = {}
        for key, caption in self.IMAGE_ROWS:
            path_value = getattr(p, f"image_{key}")
            mode_value = getattr(p, f"image_{key}_mode")
            self.image_path_vars[key] = tk.StringVar(value=path_value)
            self.image_name_vars[key] = tk.StringVar(value=Path(path_value).name if path_value else "기본 이미지")
            self.image_mode_vars[key] = tk.StringVar(value="가운데 크롭" if mode_value == "crop" else "자동 맞춤")

            row = tk.Frame(content, bg=core.PANEL)
            row.pack(fill="x", pady=2, **pad)
            self._label(row, caption, size=9, bg=core.PANEL).pack(side="left")
            self._label(row, textvariable=self.image_name_vars[key], size=8, fg=core.MUTED, bg=core.PANEL) if False else None
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


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    CompactDesktopApp().run()
