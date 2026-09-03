from __future__ import annotations

import os
import tkinter as tk
from PIL import Image, ImageTk

import app as core
from app import App, SingleInstance
from asset_manager import resolve_asset
from messages import pick
from settings import UserSettings, set_windows_startup


class DesktopApp(App):
    """Desktop-first UI shell wired to the existing timer engine and state."""

    def __init__(self):
        super().__init__()
        self.root.geometry("940x610")
        self.root.minsize(900, 580)

    def _image_on(self, path, max_size, bg):
        if not path:
            return self._fallback_character()
        with Image.open(path) as src:
            rgba = src.convert("RGBA")
            rgba.thumbnail(max_size, Image.Resampling.LANCZOS)
            canvas = Image.new("RGBA", rgba.size, bg)
            canvas.alpha_composite(rgba)
            return canvas.convert("RGB")

    def _set_small_avatar(self, target):
        try:
            image = self._image_on(resolve_asset("master_face"), (34, 34), core.BG)
            image.thumbnail((34, 34), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (34, 34), core.BG)
            canvas.paste(image, ((34 - image.width) // 2, (34 - image.height) // 2))
            photo = ImageTk.PhotoImage(canvas)
            target.image = photo
            target.configure(image=photo)
        except Exception:
            core.log.exception("avatar asset failed")

    def _load_character_image(self, role: str, max_size=(430, 455)):
        return self._image_on(resolve_asset(role), max_size, core.PANEL)

    def _build_header(self, parent, title, back_command=None, settings_command=None):
        row = tk.Frame(parent, bg=core.BG, height=58)
        row.pack(fill="x", padx=20, pady=(14, 4))
        row.pack_propagate(False)

        if back_command:
            self._button(row, "‹", back_command, width=2).pack(side="left", padx=(0, 8))

        avatar = tk.Label(row, bg=core.BG, bd=0)
        avatar.pack(side="left", padx=(0, 9))
        self._set_small_avatar(avatar)

        self._label(row, title, size=12, weight="bold").pack(side="left")
        if title == "경희 타이머":
            self._label(row, "●", size=9, fg=core.GREEN).pack(side="left", padx=(10, 4))
            self.header_status = self._label(row, "집중 중", size=9, fg=core.MUTED)
            self.header_status.pack(side="left")

        if settings_command:
            self._button(row, "설정", settings_command).pack(side="right")

    def _build_timer_page(self):
        page = self.timer_page
        self._build_header(page, "경희 타이머", settings_command=lambda: self._show_page("settings"))

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=20, pady=(4, 18))
        body.grid_columnconfigure(0, weight=10, uniform="main")
        body.grid_columnconfigure(1, weight=11, uniform="main")
        body.grid_rowconfigure(0, weight=1)

        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)

        top = tk.Frame(left, bg=core.PANEL)
        top.pack(fill="x", padx=22, pady=(20, 8))
        self._label(top, "연속 집중 시간", size=10, weight="bold", fg=core.MUTED, bg=core.PANEL).pack(anchor="w")
        self.cont = self._label(top, "00:00:00", size=32, weight="bold", bg=core.PANEL)
        self.cont.pack(anchor="w", pady=(5, 0))
        self._label(top, "오늘 목표: 09:00:00", size=9, fg=core.MUTED, bg=core.PANEL).pack(anchor="w", pady=(2, 0))
        self.status = self._label(top, "현재 사용 중", size=9, weight="bold", fg=core.GREEN, bg=core.PANEL)
        self.status.pack(anchor="w", pady=(5, 0))

        progress_wrap = tk.Frame(left, bg=core.PANEL)
        progress_wrap.pack(fill="x", padx=22, pady=(10, 14))
        self.progress_canvas = tk.Canvas(progress_wrap, height=9, bg=core.PANEL_2, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x")
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 9, fill=core.PURPLE, outline="")
        self.progress_canvas.bind("<Configure>", lambda _e: self._update_progress())
        progress_text = tk.Frame(progress_wrap, bg=core.PANEL)
        progress_text.pack(fill="x", pady=(5, 0))
        self._label(progress_text, "다음 휴식까지", size=9, fg=core.MUTED, bg=core.PANEL).pack(side="left")
        self.remain = self._label(progress_text, "60분", size=9, weight="bold", fg=core.TEXT, bg=core.PANEL)
        self.remain.pack(side="right")

        metrics = tk.Frame(left, bg=core.PANEL)
        metrics.pack(fill="x", padx=22, pady=(0, 14))
        for i in range(3):
            metrics.grid_columnconfigure(i, weight=1)
        self.today_active = self._metric(metrics, 0, "오늘 실사용")
        self.today_away = self._metric(metrics, 1, "자리비움")
        self.today_ratio = self._metric(metrics, 2, "실사용률")

        actions = tk.Frame(left, bg=core.PANEL)
        actions.pack(fill="x", padx=22, pady=(0, 12))
        self.away_btn = self._button(actions, "자리비움 시작", self.toggle_manual_away, primary=True)
        self.away_btn.pack(side="left", fill="x", expand=True, padx=(0, 5))
        self._button(actions, "오늘 기록", self.show_stats).pack(side="left", fill="x", expand=True, padx=(5, 0))

        footer = self._card(left, bg=core.PANEL_2)
        footer.pack(fill="x", padx=22, pady=(0, 20))
        self.next_break = self._label(footer, "다음 휴식 알림: 60분 후", size=9, fg=core.MUTED, bg=core.PANEL_2)
        self.next_break.pack(side="left", padx=12, pady=10)

        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.character = tk.Label(right, bg=core.PANEL, bd=0, anchor="s")
        self.character.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 0))

        bubble = tk.Frame(right, bg="#211644", highlightthickness=1, highlightbackground="#523A8E")
        bubble.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))
        self.speech = tk.Label(
            bubble,
            text=pick("playful"),
            wraplength=390,
            justify="left",
            font=("Malgun Gothic", 11, "bold"),
            fg=core.TEXT,
            bg="#211644",
            padx=14,
            pady=11,
        )
        self.speech.pack(fill="x")

    def _build_stats_page(self):
        page = self.stats_page
        self._build_header(page, "오늘 기록", back_command=lambda: self._show_page("timer"))

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=20, pady=(4, 18))
        body.grid_columnconfigure(0, weight=7, uniform="stats")
        body.grid_columnconfigure(1, weight=13, uniform="stats")
        body.grid_rowconfigure(0, weight=1)

        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._label(left, "오늘 집중 요약", size=11, weight="bold", fg=core.MUTED, bg=core.PANEL).pack(anchor="w", padx=20, pady=(20, 8))

        self.stats_values = {}
        rows = [
            ("active", "실사용 시간"),
            ("away", "자리비움 시간"),
            ("count", "휴식 횟수"),
            ("longest", "최장 연속 사용"),
            ("ratio", "실사용률"),
        ]
        for key, caption in rows:
            row = tk.Frame(left, bg=core.PANEL)
            row.pack(fill="x", padx=20, pady=9)
            self._label(row, caption, size=9, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            value = self._label(row, "-", size=13, weight="bold", bg=core.PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self._button(left, "타이머로 돌아가기", lambda: self._show_page("timer")).pack(side="bottom", fill="x", padx=20, pady=20)

        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)
        self.stats_character = tk.Label(right, bg=core.PANEL, bd=0, anchor="s")
        self.stats_character.grid(row=0, column=0, sticky="nsew", padx=6, pady=(4, 0))
        self.stats_speech = tk.Label(
            right,
            text=pick("stats"),
            wraplength=440,
            justify="left",
            font=("Malgun Gothic", 11, "bold"),
            fg=core.TEXT,
            bg="#211644",
            padx=16,
            pady=12,
        )
        self.stats_speech.grid(row=1, column=0, sticky="ew", padx=18, pady=(0, 16))

    def _set_stats_character(self):
        try:
            image = self._load_character_image("stats", (500, 455))
            self.stats_photo = ImageTk.PhotoImage(image)
            self.stats_character.configure(image=self.stats_photo)
        except Exception:
            core.log.exception("stats character asset failed")

    def _build_settings_page(self):
        page = self.settings_page
        self._build_header(page, "설정", back_command=lambda: self._show_page("timer"))

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=20, pady=(4, 18))

        nav = self._card(body, width=160)
        nav.pack(side="left", fill="y", padx=(0, 8))
        nav.pack_propagate(False)
        for index, caption in enumerate(("일반 설정", "알림 설정", "시간 설정")):
            self._label(
                nav,
                caption,
                size=9,
                weight="bold" if index == 0 else "normal",
                fg=core.TEXT if index == 0 else core.MUTED,
                bg="#2B2348" if index == 0 else core.PANEL,
                anchor="w",
                padx=14,
                pady=11,
            ).pack(fill="x", padx=8, pady=(8 if index == 0 else 0, 0))

        panel = self._card(body)
        panel.pack(side="left", fill="both", expand=True, padx=(8, 0))

        content = tk.Frame(panel, bg=core.PANEL)
        content.pack(side="left", fill="both", expand=True, padx=20, pady=18)
        self._label(content, "일반 설정", size=11, weight="bold", bg=core.PANEL).pack(anchor="w", pady=(0, 10))
        self._label(content, "체크와 시간을 바꾼 뒤 저장해 주세요.", size=8, fg=core.MUTED, bg=core.PANEL).pack(anchor="w", pady=(0, 8))

        p = self.preferences
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
                content,
                text=caption,
                variable=self.settings_bool_vars[key],
                font=("Malgun Gothic", 9),
                fg=core.TEXT,
                bg=core.PANEL,
                activeforeground=core.TEXT,
                activebackground=core.PANEL,
                selectcolor=core.PANEL_2,
                highlightthickness=0,
                bd=0,
                cursor="hand2",
            ).pack(anchor="w", pady=3)

        self._label(content, "퇴근 시간 설정", size=10, weight="bold", bg=core.PANEL).pack(anchor="w", pady=(20, 8))
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
            row.pack(fill="x", pady=4)
            self._label(row, caption, size=9, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            tk.Entry(
                row,
                textvariable=self.settings_time_vars[key],
                width=7,
                justify="center",
                font=("Malgun Gothic", 9, "bold"),
                fg=core.TEXT,
                bg=core.PANEL_2,
                insertbackground=core.TEXT,
                relief="flat",
                bd=0,
            ).pack(side="right", ipady=4)

        save_row = tk.Frame(content, bg=core.PANEL)
        save_row.pack(fill="x", pady=(15, 0))
        self.settings_status = self._label(save_row, "", size=8, fg=core.GREEN, bg=core.PANEL)
        self.settings_status.pack(side="left")
        self._button(save_row, "설정 저장", self._save_settings, primary=True).pack(side="right")

        image_holder = tk.Label(panel, bg=core.PANEL, bd=0, anchor="s")
        image_holder.pack(side="right", fill="y", padx=(4, 10), pady=(10, 0))
        try:
            image = self._load_character_image("settings", (270, 420))
            self.settings_photo = ImageTk.PhotoImage(image)
            image_holder.configure(image=self.settings_photo)
        except Exception:
            core.log.exception("settings character asset failed")

    def _save_settings(self):
        candidate = UserSettings(
            start_with_windows=self.settings_bool_vars["start_with_windows"].get(),
            always_on_top=self.settings_bool_vars["always_on_top"].get(),
            break_reminders=self.settings_bool_vars["break_reminders"].get(),
            workday_reminders=self.settings_bool_vars["workday_reminders"].get(),
            wind_down=self.settings_time_vars["wind_down"].get().strip(),
            leave_mode=self.settings_time_vars["leave_mode"].get().strip(),
            strong_leave=self.settings_time_vars["strong_leave"].get().strip(),
            late_leave=self.settings_time_vars["late_leave"].get().strip(),
        )
        try:
            candidate.workday_policy()
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
        self.settings_status.configure(text="저장됨", fg=core.GREEN)

    def _update_ui(self):
        super()._update_ui()
        if hasattr(self, "header_status"):
            self.header_status.configure(
                text="자리비움 중" if self.state.session.is_away else "집중 중",
                fg=core.AMBER if self.state.session.is_away else core.MUTED,
            )

    def show_break_toast(self, text, allow_snooze=True):
        self._destroy_toast()
        win = self._toast_window(500, 184)
        self._toast_character(win, "rest")

        text_wrap = tk.Frame(win, bg=core.PANEL)
        text_wrap.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._label(text_wrap, "휴식할 시간이에요", size=10, weight="bold", fg=core.GREEN, bg=core.PANEL).pack(anchor="w")
        self._label(text_wrap, text, size=9, bg=core.PANEL, wraplength=320, justify="left").pack(anchor="w", pady=(3, 8))
        row = tk.Frame(text_wrap, bg=core.PANEL)
        row.pack(anchor="w")
        self._button(row, "알았어, 쉴게", self.accept_break, primary=True).pack(side="left", padx=(0, 6))
        if allow_snooze:
            self._button(row, "5분 더", self.snooze_break).pack(side="left")


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    if os.name != "nt":
        raise SystemExit("Windows only")
    DesktopApp().run()
