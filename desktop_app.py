from __future__ import annotations

import os
import time
import tkinter as tk
from PIL import Image, ImageTk

import app as core
from app import App, SingleInstance
from asset_manager import resolve_asset
from messages import pick
from settings import UserSettings, set_windows_startup


class DesktopApp(App):
    """Desktop-first UI shell wired to the existing timer engine and state."""

    TRANSPARENT_KEY = "#010203"
    COMPACT_SIZE = (460, 430)
    DETAIL_SIZE = (560, 430)

    def __init__(self):
        super().__init__()
        self._enable_compact_transparency()
        self._resize_for_page(self.current_page)

    def _enable_compact_transparency(self):
        try:
            self.root.configure(bg=self.TRANSPARENT_KEY)
            self.root.wm_attributes("-transparentcolor", self.TRANSPARENT_KEY)
        except tk.TclError:
            # The packaged app is Windows-only, but keep the UI usable if a
            # particular Tk build does not expose colour-key transparency.
            core.log.exception("window transparency is unavailable")

    def _resize_for_page(self, name: str):
        width, height = self.COMPACT_SIZE if name == "timer" else self.DETAIL_SIZE
        self.root.minsize(width, height)
        self.root.geometry(f"{width}x{height}")

    def _show_page(self, name: str):
        super()._show_page(name)
        self._resize_for_page(name)

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
            image = self._image_on(resolve_asset("master_face"), (26, 26), core.BG)
            image.thumbnail((26, 26), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (26, 26), core.BG)
            canvas.paste(image, ((26 - image.width) // 2, (26 - image.height) // 2))
            photo = ImageTk.PhotoImage(canvas)
            target.image = photo
            target.configure(image=photo)
        except Exception:
            core.log.exception("avatar asset failed")

    def _load_character_image(self, role: str, max_size=(470, 300), preserve_alpha=False):
        if preserve_alpha:
            path = resolve_asset(role)
            if path:
                with Image.open(path) as src:
                    image = src.convert("RGBA")
                    image.thumbnail(max_size, Image.Resampling.LANCZOS)
                    return image
        return self._image_on(resolve_asset(role), max_size, core.PANEL)

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            image = self._load_character_image(role, (470, 300), preserve_alpha=True)
            self.character_photo = ImageTk.PhotoImage(image)
            self.character.configure(image=self.character_photo)
            self.character_role = role
        except Exception:
            core.log.exception("character asset failed: %s", role)

    def _button(self, parent, text, command, primary=False, width=None):
        button = super()._button(parent, text, command, primary=primary, width=width)
        button.configure(font=("Malgun Gothic", 9, "bold"), padx=9, pady=5)
        return button

    def _build_header(self, parent, title, back_command=None, settings_command=None):
        row = tk.Frame(parent, bg=core.BG, height=38)
        row.pack(fill="x", padx=7, pady=(5, 2))
        row.pack_propagate(False)

        if back_command:
            self._button(row, "‹", back_command, width=2).pack(side="left", padx=(0, 5))

        avatar = tk.Label(row, bg=core.BG, bd=0)
        avatar.pack(side="left", padx=(0, 6))
        self._set_small_avatar(avatar)

        self._label(row, title, size=10, weight="bold").pack(side="left")
        if title == "경희 타이머":
            self._label(row, "●", size=7, fg=core.GREEN).pack(side="left", padx=(7, 3))
            self.header_status = self._label(row, "집중 중", size=8, fg=core.MUTED)
            self.header_status.pack(side="left")

        if settings_command:
            self._button(row, "설정", settings_command).pack(side="right")

    def _build_timer_page(self):
        page = self.timer_page
        page.configure(bg=self.TRANSPARENT_KEY)
        hero = tk.Frame(page, bg=self.TRANSPARENT_KEY, bd=0, highlightthickness=0)
        hero.pack(fill="both", expand=True)

        # Keep the label at the image's requested size.  Expanding it to fill
        # the page would turn the surrounding empty area into a click target.
        self.character = tk.Label(hero, bg=self.TRANSPARENT_KEY, bd=0, cursor="hand2")
        self.character.place(relx=0.5, rely=1.0, y=-54, anchor="s")

        clock = tk.Frame(hero, bg=core.PANEL_2, highlightthickness=1, highlightbackground=core.BORDER, cursor="hand2")
        clock.place(x=8, y=8)
        self.cont = self._label(clock, "00:00:00", size=18, weight="bold", bg=core.PANEL_2, cursor="hand2")
        self.cont.pack(padx=9, pady=(4, 0))
        self.main_status = self._label(clock, "집중 중 · 상세 보기", size=7, fg=core.GREEN, bg=core.PANEL_2, cursor="hand2")
        self.main_status.pack(pady=(0, 4))

        bubble = tk.Frame(hero, bg="#211644", highlightthickness=1, highlightbackground="#523A8E", cursor="hand2")
        bubble.place(relx=0.5, rely=1.0, y=-7, anchor="s", width=430)
        self.speech = tk.Label(
            bubble,
            text=pick("playful"),
            wraplength=400,
            justify="center",
            font=("Malgun Gothic", 9, "bold"),
            fg=core.TEXT,
            bg="#211644",
            padx=8,
            pady=7,
            cursor="hand2",
        )
        self.speech.pack(fill="x")

        for widget in (clock, self.cont, self.main_status):
            widget.bind("<Button-1>", lambda _event: self.show_stats())
        self.character.bind("<Button-1>", lambda _event: self.show_stats())
        for widget in (bubble, self.speech):
            widget.bind("<Button-1>", self._cycle_message)

    def _cycle_message(self, _event=None):
        mode = self._current_workday_state().mode
        if mode != "normal":
            kind = mode
        elif self.state.session.is_away:
            kind = "away_start"
        else:
            remaining = self.engine.remaining_to_break()
            kind = "cheer" if remaining <= 15 * 60 else "playful"
        self.speech.configure(text=pick(kind))
        self.last_dialogue_at = time.monotonic()

    def _build_stats_page(self):
        page = self.stats_page
        self._build_header(
            page,
            "상세 정보",
            back_command=lambda: self._show_page("timer"),
            settings_command=lambda: self._show_page("settings"),
        )

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=7, pady=(2, 7))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)

        panel = self._card(body)
        panel.grid(row=0, column=0, sticky="nsew")

        summary = tk.Frame(panel, bg=core.PANEL)
        summary.pack(fill="x", padx=12, pady=(8, 4))
        self.detail_cont = self._label(summary, "00:00:00", size=20, weight="bold", bg=core.PANEL)
        self.detail_cont.pack(side="left")
        self.status = self._label(summary, "현재 사용 중", size=8, weight="bold", fg=core.GREEN, bg=core.PANEL)
        self.status.pack(side="right")

        progress_wrap = tk.Frame(panel, bg=core.PANEL)
        progress_wrap.pack(fill="x", padx=12, pady=(1, 5))
        progress_text = tk.Frame(progress_wrap, bg=core.PANEL)
        progress_text.pack(fill="x")
        self._label(progress_text, "다음 휴식까지", size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
        self.remain = self._label(progress_text, "60분", size=8, weight="bold", bg=core.PANEL)
        self.remain.pack(side="right")
        self.progress_canvas = tk.Canvas(progress_wrap, height=6, bg=core.PANEL_2, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x", pady=(3, 0))
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 6, fill=core.PURPLE, outline="")
        self.progress_canvas.bind("<Configure>", lambda _e: self._update_progress())

        metrics = tk.Frame(panel, bg=core.PANEL)
        metrics.pack(fill="x", padx=12, pady=(1, 5))
        for i in range(3):
            metrics.grid_columnconfigure(i, weight=1)
        self.today_active = self._metric(metrics, 0, "오늘 실사용")
        self.today_away = self._metric(metrics, 1, "자리비움")
        self.today_ratio = self._metric(metrics, 2, "실사용률")

        self.stats_values = {}
        for key, caption in (
            ("count", "휴식 횟수"),
            ("longest", "최장 연속 사용"),
        ):
            row = tk.Frame(panel, bg=core.PANEL)
            row.pack(fill="x", padx=12, pady=1)
            self._label(row, caption, size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            value = self._label(row, "-", size=9, weight="bold", bg=core.PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self._label(panel, "최근 7일", size=8, weight="bold", fg=core.MUTED, bg=core.PANEL).pack(
            anchor="w", padx=12, pady=(5, 1)
        )
        for key, caption in (
            ("week_active", "7일 실사용"),
            ("week_average", "기록일 평균"),
            ("week_best", "최고 집중일"),
        ):
            row = tk.Frame(panel, bg=core.PANEL)
            row.pack(fill="x", padx=12, pady=1)
            self._label(row, caption, size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
            value = self._label(row, "-", size=9, weight="bold", bg=core.PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self.stats_reaction = self._label(
            panel,
            "",
            size=8,
            fg=core.TEXT,
            bg=core.PANEL_2,
            wraplength=350,
            justify="left",
        )
        self.stats_reaction.pack(fill="x", padx=12, pady=(5, 3), ipadx=7, ipady=4)

        actions = tk.Frame(panel, bg=core.PANEL)
        actions.pack(fill="x", padx=12, pady=(3, 4))
        self.away_btn = self._button(actions, "자리비움 시작", self.toggle_manual_away, primary=True)
        self.away_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._button(actions, "기본 화면", lambda: self._show_page("timer")).pack(
            side="left", fill="x", expand=True, padx=(4, 0)
        )

        footer = self._card(panel, bg=core.PANEL_2)
        footer.pack(fill="x", padx=12, pady=(0, 8))
        self.next_break = self._label(footer, "다음 휴식 알림: 60분 후", size=8, fg=core.MUTED, bg=core.PANEL_2)
        self.next_break.pack(side="left", padx=8, pady=4)

    def _update_stats_page(self, refresh_image=True):
        from stats_summary import stats_reaction, summarize_recent

        d = self.state.daily
        self.stats_values["count"].configure(text=f"{d.away_count}회")
        self.stats_values["longest"].configure(text=core.fmt(d.longest_continuous_today))

        recent = summarize_recent(self.state, days=7)
        self.stats_values["week_active"].configure(text=core.fmt(recent.active_seconds))
        average_text = core.fmt(recent.average_active_seconds) if recent.tracked_days else "-"
        self.stats_values["week_average"].configure(text=average_text)
        if recent.best_day:
            try:
                _, month, day = recent.best_day.split("-")
                best_day = f"{int(month)}/{int(day)} · {core.fmt(recent.best_day_active_seconds)}"
            except (ValueError, TypeError):
                best_day = core.fmt(recent.best_day_active_seconds)
        else:
            best_day = "-"
        self.stats_values["week_best"].configure(text=best_day)
        self.stats_reaction.configure(text=stats_reaction(recent))

    def _build_settings_page(self):
        page = self.settings_page
        self._build_header(page, "설정", back_command=lambda: self._show_page("timer"))

        body = tk.Frame(page, bg=core.BG)
        body.pack(fill="both", expand=True, padx=7, pady=(2, 7))

        panel = self._card(body)
        panel.pack(fill="both", expand=True)

        content = tk.Frame(panel, bg=core.PANEL)
        content.pack(side="left", fill="both", expand=True, padx=12, pady=9)
        self._label(content, "앱 설정", size=10, weight="bold", bg=core.PANEL).pack(anchor="w", pady=(0, 3))

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
            ).pack(anchor="w", pady=0)

        self._label(content, "퇴근 시간 설정", size=9, weight="bold", bg=core.PANEL).pack(anchor="w", pady=(6, 3))
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
            row.pack(fill="x", pady=1)
            self._label(row, caption, size=8, fg=core.MUTED, bg=core.PANEL).pack(side="left")
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
            ).pack(side="right", ipady=1)

        save_row = tk.Frame(content, bg=core.PANEL)
        save_row.pack(fill="x", pady=(5, 0))
        self.settings_status = self._label(save_row, "", size=8, fg=core.GREEN, bg=core.PANEL)
        self.settings_status.pack(side="left")
        self._button(save_row, "설정 저장", self._save_settings, primary=True).pack(side="right")

        image_holder = tk.Label(panel, bg=core.PANEL, bd=0, anchor="s")
        image_holder.pack(side="right", fill="y", padx=(2, 5), pady=(5, 0))
        try:
            image = self._load_character_image("settings", (150, 300))
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
        self.detail_cont.configure(text=self.cont.cget("text"))
        self.main_status.configure(
            text=("자리비움 중" if self.state.session.is_away else "집중 중") + " · 상세 보기",
            fg=core.AMBER if self.state.session.is_away else core.GREEN,
        )
        if hasattr(self, "header_status"):
            self.header_status.configure(
                text="자리비움 중" if self.state.session.is_away else "집중 중",
                fg=core.AMBER if self.state.session.is_away else core.MUTED,
            )

    def show_break_toast(self, text, allow_snooze=True):
        self._destroy_toast()
        win = self._toast_window(420, 158)
        self._toast_character(win, "rest")

        text_wrap = tk.Frame(win, bg=core.PANEL)
        text_wrap.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._label(text_wrap, "휴식할 시간이에요", size=10, weight="bold", fg=core.GREEN, bg=core.PANEL).pack(anchor="w")
        self._label(text_wrap, text, size=9, bg=core.PANEL, wraplength=250, justify="left").pack(anchor="w", pady=(3, 8))
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
