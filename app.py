from __future__ import annotations

import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk

from PIL import Image, ImageDraw, ImageTk
import pystray
from pystray import MenuItem as item

from asset_manager import resolve_asset, role_for_dialogue, role_for_work_mode
from break_reminder import BreakReminderGate
from messages import pick
from settings import UserSettings, load_user_settings, save_user_settings
from state import load_state, save_state, rollover_daily, prepare_startup_state
from timer_engine import BREAK_INTERVAL_SEC, TimerEngine
from workday import WorkdayState, apply_reminder_preference, classify_workday, should_encourage_more_work

APP_NAME = "경희 타이머"
DIALOGUE_INTERVAL_SEC = 60

DATA_DIR = Path(os.getenv("APPDATA", Path.home())) / "KyungheeAssistant"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
SETTINGS_FILE = DATA_DIR / "settings.json"
LOG_FILE = DATA_DIR / "kyunghee.log"

BG = "#070B1B"
PANEL = "#0E1528"
PANEL_2 = "#121B31"
BORDER = "#202A44"
TEXT = "#F5F7FF"
MUTED = "#9AA5BD"
PURPLE = "#7C4DFF"
PURPLE_2 = "#5D35D6"
GREEN = "#4ADE80"
AMBER = "#F59E0B"

log = logging.getLogger("kyunghee")
log.setLevel(logging.INFO)
if not log.handlers:
    h = RotatingFileHandler(LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)


def fmt(sec: float) -> str:
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    if h:
        return f"{h}시간 {m}분"
    if m:
        return f"{m}분 {s}초"
    return f"{s}초"


def fmt_clock(sec: float) -> str:
    sec = max(0, int(sec))
    h, r = divmod(sec, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


class SingleInstance:
    def __init__(self):
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.CreateMutexW.restype = ctypes.c_void_p
        self.handle = k32.CreateMutexW(None, False, "Local\\KyungheeAssistantSingleton")
        err = ctypes.get_last_error()
        return bool(self.handle) and err != 183


class App:
    def __init__(self):
        self.preferences = load_user_settings(SETTINGS_FILE)
        self.workday_policy = self.preferences.workday_policy()
        self.state = load_state(STATE_FILE)
        prepare_startup_state(self.state, time.time())
        self.engine = TimerEngine(self.state)
        self.break_gate = BreakReminderGate()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("760x520")
        self.root.minsize(720, 500)
        self.root.configure(bg=BG)
        self.root.attributes("-topmost", self.preferences.always_on_top)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)

        self.ui_commands: queue.Queue = queue.Queue()
        self.toast = None
        self.tray_icon = None
        self.last_work_mode = "normal"
        self.last_dialogue_at = time.monotonic()
        self.character_photo = None
        self.character_role = None
        self.stats_photo = None
        self.avatar_photo = None
        self.toast_photo = None
        self.current_page = "timer"

        self._build_ui()
        initial = self._current_workday_state()
        self.last_work_mode = initial.mode
        self._set_character(role_for_work_mode(initial.mode))
        if initial.mode != "normal":
            self.speech.configure(text=pick(initial.mode))

        self._start_tray()
        self.root.after(250, self._drain_ui_queue)
        self.root.after(1000, self._tick_safe)
        self.root.after(5000, self._save_periodic)

    def _current_workday_state(self) -> WorkdayState:
        return apply_reminder_preference(
            classify_workday(
                datetime.now(),
                self.state.daily.active_seconds,
                self.workday_policy,
            ),
            self.preferences.workday_reminders,
        )

    def apply_preferences(self, preferences: UserSettings) -> None:
        preferences.workday_policy()
        save_user_settings(SETTINGS_FILE, preferences)
        self.preferences = preferences
        self.workday_policy = preferences.workday_policy()
        self.root.attributes("-topmost", preferences.always_on_top)

    def _label(self, parent, text="", size=10, weight="normal", fg=TEXT, bg=None, **kwargs):
        return tk.Label(
            parent,
            text=text,
            font=("Malgun Gothic", size, weight),
            fg=fg,
            bg=bg or parent.cget("bg"),
            **kwargs,
        )

    def _button(self, parent, text, command, primary=False, width=None):
        return tk.Button(
            parent,
            text=text,
            command=command,
            width=width,
            font=("Malgun Gothic", 10, "bold"),
            fg=TEXT,
            bg=PURPLE if primary else PANEL_2,
            activeforeground=TEXT,
            activebackground=PURPLE_2 if primary else BORDER,
            relief="flat",
            bd=0,
            padx=14,
            pady=9,
            cursor="hand2",
        )

    def _card(self, parent, bg=PANEL, **kwargs):
        return tk.Frame(parent, bg=bg, highlightthickness=1, highlightbackground=BORDER, **kwargs)

    def _build_header(self, parent, title, back_command=None, settings_command=None):
        row = tk.Frame(parent, bg=BG, height=48)
        row.pack(fill="x", padx=18, pady=(12, 4))
        row.pack_propagate(False)

        if back_command:
            self._button(row, "‹", back_command, width=2).pack(side="left", padx=(0, 8))

        avatar = tk.Label(row, bg=BG, bd=0)
        avatar.pack(side="left", padx=(0, 8))
        self._set_small_avatar(avatar)

        self._label(row, title, size=11, weight="bold").pack(side="left")
        if settings_command:
            self._button(row, "설정", settings_command).pack(side="right")

    def _set_small_avatar(self, target):
        try:
            path = resolve_asset("master_face")
            image = Image.open(path).convert("RGB") if path else self._fallback_character()
            image.thumbnail((32, 32), Image.Resampling.LANCZOS)
            canvas = Image.new("RGB", (32, 32), BG)
            x = (32 - image.width) // 2
            y = (32 - image.height) // 2
            canvas.paste(image, (x, y))
            photo = ImageTk.PhotoImage(canvas)
            target.image = photo
            target.configure(image=photo)
        except Exception:
            log.exception("avatar asset failed")

    def _build_ui(self):
        self.page_host = tk.Frame(self.root, bg=BG)
        self.page_host.pack(fill="both", expand=True)

        self.timer_page = tk.Frame(self.page_host, bg=BG)
        self.stats_page = tk.Frame(self.page_host, bg=BG)
        self.settings_page = tk.Frame(self.page_host, bg=BG)

        for page in (self.timer_page, self.stats_page, self.settings_page):
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_timer_page()
        self._build_stats_page()
        self._build_settings_page()
        self._show_page("timer")

    def _build_timer_page(self):
        page = self.timer_page
        self._build_header(page, "경희 타이머", settings_command=lambda: self._show_page("settings"))

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 14))
        body.grid_columnconfigure(0, weight=11, uniform="main")
        body.grid_columnconfigure(1, weight=10, uniform="main")
        body.grid_rowconfigure(0, weight=1)

        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        left.grid_columnconfigure(0, weight=1)

        top = tk.Frame(left, bg=PANEL)
        top.pack(fill="x", padx=20, pady=(18, 8))
        self._label(top, "연속 집중 시간", size=10, weight="bold", fg=MUTED, bg=PANEL).pack(anchor="w")
        self.cont = self._label(top, "00:00:00", size=30, weight="bold", bg=PANEL)
        self.cont.pack(anchor="w", pady=(4, 1))

        self.status = self._label(top, "사용 중", size=9, weight="bold", fg=GREEN, bg=PANEL)
        self.status.pack(anchor="w")

        progress_wrap = tk.Frame(left, bg=PANEL)
        progress_wrap.pack(fill="x", padx=20, pady=(10, 14))
        row = tk.Frame(progress_wrap, bg=PANEL)
        row.pack(fill="x")
        self._label(row, "다음 휴식까지", size=9, fg=MUTED, bg=PANEL).pack(side="left")
        self.remain = self._label(row, "60분", size=9, weight="bold", fg=TEXT, bg=PANEL)
        self.remain.pack(side="right")

        self.progress_canvas = tk.Canvas(progress_wrap, height=9, bg=PANEL_2, highlightthickness=0, bd=0)
        self.progress_canvas.pack(fill="x", pady=(7, 0))
        self.progress_bar = self.progress_canvas.create_rectangle(0, 0, 0, 9, fill=PURPLE, outline="")
        self.progress_canvas.bind("<Configure>", lambda _e: self._update_progress())

        stats = tk.Frame(left, bg=PANEL)
        stats.pack(fill="x", padx=20, pady=(4, 14))
        for i in range(3):
            stats.grid_columnconfigure(i, weight=1)

        self.today_active = self._metric(stats, 0, "오늘 실사용")
        self.today_away = self._metric(stats, 1, "자리비움")
        self.today_ratio = self._metric(stats, 2, "실사용률")

        buttons = tk.Frame(left, bg=PANEL)
        buttons.pack(fill="x", padx=20, pady=(2, 12))
        self.away_btn = self._button(buttons, "자리비움 시작", self.toggle_manual_away, primary=True)
        self.away_btn.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self._button(buttons, "오늘 기록", self.show_stats).pack(side="left", fill="x", expand=True, padx=(6, 0))

        footer = self._card(left, bg=PANEL_2)
        footer.pack(fill="x", padx=20, pady=(4, 18))
        self.next_break = self._label(footer, "다음 휴식 알림: 60분 후", size=9, fg=MUTED, bg=PANEL_2)
        self.next_break.pack(side="left", padx=12, pady=10)

        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.character = tk.Label(right, bg=PANEL, bd=0, anchor="s")
        self.character.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 0))

        self.speech = tk.Label(
            right,
            text=pick("playful"),
            wraplength=280,
            justify="left",
            font=("Malgun Gothic", 10, "bold"),
            fg=TEXT,
            bg="#24164B",
            padx=14,
            pady=10,
        )
        self.speech.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))

    def _metric(self, parent, column, caption):
        card = tk.Frame(parent, bg=PANEL_2, highlightthickness=1, highlightbackground=BORDER)
        card.grid(row=0, column=column, sticky="nsew", padx=(0 if column == 0 else 4, 0 if column == 2 else 4))
        value = self._label(card, "-", size=12, weight="bold", bg=PANEL_2)
        value.pack(pady=(10, 0))
        self._label(card, caption, size=8, fg=MUTED, bg=PANEL_2).pack(pady=(1, 9))
        return value

    def _build_stats_page(self):
        page = self.stats_page
        self._build_header(page, "오늘 기록", back_command=lambda: self._show_page("timer"))

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 14))
        body.grid_columnconfigure(0, weight=8, uniform="stats")
        body.grid_columnconfigure(1, weight=12, uniform="stats")
        body.grid_rowconfigure(0, weight=1)

        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self._label(left, "오늘 집중 요약", size=10, weight="bold", fg=MUTED, bg=PANEL).pack(anchor="w", padx=18, pady=(18, 6))

        self.stats_values = {}
        rows = [
            ("active", "실사용 시간"),
            ("away", "자리비움 시간"),
            ("count", "휴식 횟수"),
            ("longest", "최장 연속 사용"),
            ("ratio", "실사용률"),
        ]
        for key, label in rows:
            row = tk.Frame(left, bg=PANEL)
            row.pack(fill="x", padx=18, pady=7)
            self._label(row, label, size=9, fg=MUTED, bg=PANEL).pack(side="left")
            value = self._label(row, "-", size=11, weight="bold", fg=TEXT, bg=PANEL)
            value.pack(side="right")
            self.stats_values[key] = value

        self._button(left, "타이머로 돌아가기", lambda: self._show_page("timer")).pack(
            side="bottom", fill="x", padx=18, pady=18
        )

        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        right.grid_rowconfigure(0, weight=1)
        right.grid_columnconfigure(0, weight=1)

        self.stats_character = tk.Label(right, bg=PANEL, bd=0, anchor="s")
        self.stats_character.grid(row=0, column=0, sticky="nsew", padx=4, pady=(4, 0))

        self.stats_speech = tk.Label(
            right,
            text=pick("stats"),
            wraplength=360,
            justify="left",
            font=("Malgun Gothic", 10, "bold"),
            fg=TEXT,
            bg="#24164B",
            padx=14,
            pady=10,
        )
        self.stats_speech.grid(row=1, column=0, sticky="ew", padx=14, pady=(0, 14))

    def _build_settings_page(self):
        page = self.settings_page
        self._build_header(page, "설정", back_command=lambda: self._show_page("timer"))

        body = tk.Frame(page, bg=BG)
        body.pack(fill="both", expand=True, padx=18, pady=(4, 14))

        left = self._card(body, width=150)
        left.pack(side="left", fill="y", padx=(0, 8))
        left.pack_propagate(False)
        for label in ("일반", "알림 설정", "시간 설정", "기타"):
            active = label == "일반"
            self._label(
                left,
                label,
                size=9,
                weight="bold" if active else "normal",
                fg=TEXT if active else MUTED,
                bg="#2B2348" if active else PANEL,
                anchor="w",
                padx=14,
                pady=10,
            ).pack(fill="x", padx=8, pady=(8 if active else 0, 0))

        right = self._card(body)
        right.pack(side="left", fill="both", expand=True, padx=(8, 0))
        self._label(right, "기본 설정", size=11, weight="bold", bg=PANEL).pack(anchor="w", padx=20, pady=(18, 10))

        for text in ("Windows 시작 시 자동 실행", "메인 창 항상 위 표시", "휴식 알림 사용", "퇴근 시간 알림 사용"):
            row = tk.Frame(right, bg=PANEL)
            row.pack(fill="x", padx=20, pady=6)
            self._label(row, "✓", size=11, weight="bold", fg=PURPLE, bg=PANEL).pack(side="left")
            self._label(row, text, size=9, bg=PANEL).pack(side="left", padx=8)

        self._label(right, "퇴근 시간 설정", size=10, weight="bold", bg=PANEL).pack(anchor="w", padx=20, pady=(18, 8))
        schedule = (
            ("마무리 예고", "17:00"),
            ("퇴근 모드 시작", "17:30"),
            ("적극 퇴근 권고", "18:00"),
            ("야근 잔소리 시작", "18:30"),
        )
        for label, value in schedule:
            row = tk.Frame(right, bg=PANEL)
            row.pack(fill="x", padx=20, pady=4)
            self._label(row, label, size=9, fg=MUTED, bg=PANEL).pack(side="left")
            self._label(row, value, size=9, weight="bold", bg=PANEL).pack(side="right")

        self._label(
            right,
            "현재 0.4.0-alpha에서는 위 시간 정책을 표시만 합니다. 변경 기능은 다음 단계에서 연결합니다.",
            size=8,
            fg=MUTED,
            bg=PANEL,
            wraplength=420,
            justify="left",
        ).pack(anchor="w", padx=20, pady=(18, 0))

    def _show_page(self, name: str):
        self.current_page = name
        if name == "stats":
            self._update_stats_page()
            self.stats_page.tkraise()
        elif name == "settings":
            self.settings_page.tkraise()
        else:
            self.timer_page.tkraise()

    def _fallback_character(self):
        img = Image.new("RGB", (300, 420), PANEL)
        draw = ImageDraw.Draw(img)
        draw.ellipse((95, 45, 205, 155), outline=PURPLE, width=3)
        draw.text((140, 180), "K", fill=TEXT)
        return img

    def _load_character_image(self, role: str, max_size=(310, 390)):
        path = resolve_asset(role)
        image = Image.open(path).convert("RGB") if path else self._fallback_character()
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        return image

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            image = self._load_character_image(role, (330, 400))
            self.character_photo = ImageTk.PhotoImage(image)
            self.character.configure(image=self.character_photo)
            self.character_role = role
        except Exception:
            log.exception("character asset failed: %s", role)

    def _set_stats_character(self):
        try:
            image = self._load_character_image("cheer", (420, 390))
            self.stats_photo = ImageTk.PhotoImage(image)
            self.stats_character.configure(image=self.stats_photo)
        except Exception:
            log.exception("stats character asset failed")

    def _say(self, kind: str, text: str | None = None, work_mode: str = "normal"):
        self.speech.configure(text=text or pick(kind))
        self._set_character(role_for_dialogue(kind, work_mode))
        self.last_dialogue_at = time.monotonic()

    def toggle_manual_away(self):
        if self.state.session.is_away:
            self.engine.stop_manual_away()
            self.break_gate.reset()
            self._say("return", "복귀했네. 다시 시작할게.")
        else:
            self.engine.start_manual_away()
            self.break_gate.reset()
            self._say("away_start")
        self._update_ui()

    def accept_break(self):
        self.break_gate.reset()
        self._destroy_toast()
        self.engine.accept_break()
        text = "좋아. 잠깐 쉬고 와. 시간은 내가 멈춰둘게."
        self._say("away_start", text)
        self.show_toast(text)

    def snooze_break(self):
        mode = self._current_workday_state().mode
        if not should_encourage_more_work(mode):
            # Do not re-arm the gate here: otherwise an already-due break alert
            # reappears one second later after the workday mode changes.
            self._destroy_toast()
            text = pick(mode)
            self._say(mode, text, work_mode=mode)
            self.show_toast(text)
            return

        self.break_gate.reset()
        self._destroy_toast()
        self.engine.snooze_break()
        n = self.state.session.ignored_breaks
        kind = "snooze1" if n == 1 else "snooze2"
        text = pick(kind)
        self._say(kind, text)
        self.show_toast(text)

    def _tick_safe(self):
        try:
            rollover_daily(self.state)
            result = self.engine.tick()

            if result.became_active:
                self.break_gate.reset()
                text = pick("return", away=fmt(result.away_duration))
                self._say("return", text)
                self.show_toast(text)

            now = time.monotonic()
            if not self.preferences.break_reminders:
                self.break_gate.reset()
            elif self.break_gate.should_show(result.break_due, now):
                mode = self._current_workday_state().mode
                can_snooze = should_encourage_more_work(mode)
                text = pick("break") if can_snooze else pick(mode)
                self._set_character(role_for_dialogue("break", mode))
                self.show_break_toast(text, allow_snooze=can_snooze)

            self._update_ui()
            self._update_dialogue()
            if self.current_page == "stats":
                self._update_stats_page(refresh_image=False)
        except Exception:
            log.exception("tick failed")
        finally:
            if self.root.winfo_exists():
                self.root.after(1000, self._tick_safe)

    def _update_dialogue(self):
        state = self._current_workday_state()
        now = time.monotonic()

        if state.mode != self.last_work_mode:
            self.last_work_mode = state.mode
            kind = state.mode if state.mode != "normal" else "playful"
            self._say(kind, work_mode=state.mode)
            return

        if self.state.session.is_away or now - self.last_dialogue_at < DIALOGUE_INTERVAL_SEC:
            return

        if state.mode != "normal":
            self._say(state.mode, work_mode=state.mode)
            return

        ignored = self.state.session.ignored_breaks
        if ignored >= 2:
            kind = "nag"
        elif ignored == 1:
            kind = "worry"
        elif self.engine.remaining_to_break() <= 15 * 60:
            kind = "cheer"
        else:
            kind = "playful"
        self._say(kind)

    def _update_progress(self):
        if not hasattr(self, "progress_canvas"):
            return
        width = max(1, self.progress_canvas.winfo_width())
        continuous = max(0.0, float(self.state.session.continuous_seconds))
        progress = min(1.0, continuous / BREAK_INTERVAL_SEC)
        self.progress_canvas.coords(self.progress_bar, 0, 0, width * progress, 9)

    def _update_ui(self):
        s = self.state.session
        d = self.state.daily
        total = d.active_seconds + d.away_seconds
        ratio = d.active_seconds / total * 100 if total else 0.0
        remaining = self.engine.remaining_to_break()

        self.status.configure(
            text="자리비움 중" if s.is_away else "현재 사용 중",
            fg=AMBER if s.is_away else GREEN,
        )
        self.away_btn.configure(text="복귀하기" if s.is_away else "자리비움 시작")
        self.cont.configure(text=fmt_clock(s.continuous_seconds))
        self.remain.configure(text=fmt(remaining))
        self.next_break.configure(text=f"다음 휴식 알림: {fmt(remaining)} 후")
        self.today_active.configure(text=fmt(d.active_seconds))
        self.today_away.configure(text=fmt(d.away_seconds))
        self.today_ratio.configure(text=f"{ratio:.0f}%")
        self._update_progress()

    def _update_stats_page(self, refresh_image=True):
        d = self.state.daily
        total = d.active_seconds + d.away_seconds
        ratio = d.active_seconds / total * 100 if total else 0.0
        self.stats_values["active"].configure(text=fmt(d.active_seconds))
        self.stats_values["away"].configure(text=fmt(d.away_seconds))
        self.stats_values["count"].configure(text=f"{d.away_count}회")
        self.stats_values["longest"].configure(text=fmt(d.longest_continuous_today))
        self.stats_values["ratio"].configure(text=f"{ratio:.0f}%")
        if refresh_image or self.stats_photo is None:
            self._set_stats_character()
            self.stats_speech.configure(text=pick("praise") if d.active_seconds >= 3600 else pick("stats"))

    def show_stats(self):
        self._show_page("stats")
        self.show()

    def _destroy_specific(self, win):
        try:
            if win is not None and win.winfo_exists():
                win.destroy()
        except Exception:
            pass
        if self.toast is win:
            self.toast = None

    def _destroy_toast(self):
        self._destroy_specific(self.toast)

    def _toast_window(self, width, height):
        win = tk.Toplevel(self.root)
        self.toast = win
        win.title("경희 타이머 알림")
        win.configure(bg=PANEL)
        win.attributes("-topmost", True)
        win.resizable(False, False)

        sw = win.winfo_screenwidth()
        sh = win.winfo_screenheight()
        x = max(0, sw - width - 28)
        y = max(0, sh - height - 72)
        win.geometry(f"{width}x{height}+{x}+{y}")
        return win

    def _toast_character(self, parent, role="cheer"):
        holder = tk.Label(parent, bg=PANEL, bd=0)
        holder.pack(side="left", padx=(10, 8), pady=10)
        try:
            image = self._load_character_image(role, (92, 92))
            self.toast_photo = ImageTk.PhotoImage(image)
            holder.configure(image=self.toast_photo)
        except Exception:
            log.exception("toast character failed")

    def show_toast(self, text):
        self._destroy_toast()
        win = self._toast_window(420, 132)
        self._toast_character(win, role_for_work_mode(self.last_work_mode))

        text_wrap = tk.Frame(win, bg=PANEL)
        text_wrap.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._label(text_wrap, "경희 타이머", size=9, weight="bold", fg=PURPLE, bg=PANEL).pack(anchor="w")
        self._label(text_wrap, text, size=9, bg=PANEL, wraplength=270, justify="left").pack(anchor="w", pady=(4, 0))
        win.after(8000, lambda w=win: self._destroy_specific(w))

    def show_break_toast(self, text, allow_snooze=True):
        self._destroy_toast()
        win = self._toast_window(470, 174)
        self._toast_character(win, "worry")

        text_wrap = tk.Frame(win, bg=PANEL)
        text_wrap.pack(side="left", fill="both", expand=True, padx=(0, 12), pady=12)
        self._label(text_wrap, "휴식할 시간이에요", size=10, weight="bold", fg=GREEN, bg=PANEL).pack(anchor="w")
        self._label(text_wrap, text, size=9, bg=PANEL, wraplength=300, justify="left").pack(anchor="w", pady=(3, 8))

        row = tk.Frame(text_wrap, bg=PANEL)
        row.pack(anchor="w")
        self._button(row, "알았어, 쉴게", self.accept_break, primary=True).pack(side="left", padx=(0, 6))
        if allow_snooze:
            self._button(row, "5분 더", self.snooze_break).pack(side="left")

    def _save_periodic(self):
        try:
            save_state(STATE_FILE, self.state)
        except Exception:
            log.exception("save failed")
        finally:
            if self.root.winfo_exists():
                self.root.after(5000, self._save_periodic)

    def _drain_ui_queue(self):
        try:
            while True:
                fn = self.ui_commands.get_nowait()
                try:
                    fn()
                except Exception:
                    log.exception("tray command failed")
        except queue.Empty:
            pass
        finally:
            if self.root.winfo_exists():
                self.root.after(250, self._drain_ui_queue)

    def _tray_call(self, fn):
        self.ui_commands.put(fn)

    def _make_tray_icon(self):
        path = resolve_asset("master_face")
        try:
            if path:
                image = Image.open(path).convert("RGB")
                image.thumbnail((64, 64), Image.Resampling.LANCZOS)
                canvas = Image.new("RGB", (64, 64), BG)
                canvas.paste(image, ((64 - image.width) // 2, (64 - image.height) // 2))
                return canvas
        except Exception:
            log.exception("tray asset failed")

        icon = Image.new("RGB", (64, 64), BG)
        draw = ImageDraw.Draw(icon)
        draw.ellipse((7, 7, 57, 57), outline=PURPLE, width=3)
        draw.text((20, 19), "K", fill=TEXT)
        return icon

    def _start_tray(self):
        icon = self._make_tray_icon()
        menu = pystray.Menu(
            item("열기", lambda: self._tray_call(self.show), default=True),
            item("자리비움 시작", lambda: self._tray_call(self.toggle_manual_away)),
            item("오늘 기록 보기", lambda: self._tray_call(self.show_stats)),
            item("설정", lambda: self._tray_call(lambda: (self._show_page("settings"), self.show()))),
            item("종료", lambda: self._tray_call(self.quit)),
        )
        self.tray_icon = pystray.Icon("kyunghee_assistant", icon, APP_NAME, menu)

        def run_tray():
            try:
                self.tray_icon.run()
            except Exception:
                log.exception("tray failed")

        threading.Thread(target=run_tray, daemon=True).start()

    def show(self):
        self.root.deiconify()
        self.root.lift()
        self.root.attributes("-topmost", True)
        if not self.preferences.always_on_top:
            self.root.after(60, lambda: self.root.attributes("-topmost", False))

    def quit(self):
        try:
            save_state(STATE_FILE, self.state)
        except Exception:
            log.exception("final save failed")
        if self.tray_icon:
            try:
                self.tray_icon.stop()
            except Exception:
                pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire():
        raise SystemExit(0)
    if os.name != "nt":
        raise SystemExit("Windows only")
    App().run()
