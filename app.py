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
from state import load_state, save_state, rollover_daily, prepare_startup_state
from timer_engine import TimerEngine
from workday import classify_workday, should_encourage_more_work

APP_NAME = "경희 비서"
DIALOGUE_INTERVAL_SEC = 60

DATA_DIR = Path(os.getenv("APPDATA", Path.home())) / "KyungheeAssistant"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "kyunghee.log"

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


class SingleInstance:
    def __init__(self):
        self.handle = None

    def acquire(self) -> bool:
        if os.name != "nt":
            return True
        k32 = ctypes.windll.kernel32
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.GetLastError.restype = ctypes.c_ulong
        self.handle = k32.CreateMutexW(None, False, "Local\\KyungheeAssistantSingleton")
        return bool(self.handle) and k32.GetLastError() != 183


class App:
    def __init__(self):
        self.state = load_state(STATE_FILE)
        prepare_startup_state(self.state, time.time())
        self.engine = TimerEngine(self.state)
        self.break_gate = BreakReminderGate()

        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("470x560")
        self.root.minsize(450, 540)
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)

        self.ui_commands: queue.Queue = queue.Queue()
        self.toast = None
        self.tray_icon = None
        self.last_work_mode = "normal"
        self.last_dialogue_at = time.monotonic()
        self.character_photo = None
        self.character_role = None
        self.stats_photo = None
        self.current_page = "timer"

        self._build_ui()
        initial = classify_workday(datetime.now(), self.state.daily.active_seconds)
        self.last_work_mode = initial.mode
        self._set_character(role_for_work_mode(initial.mode))
        if initial.mode != "normal":
            self.speech.configure(text=pick(initial.mode))

        self._start_tray()
        self.root.after(250, self._drain_ui_queue)
        self.root.after(1000, self._tick_safe)
        self.root.after(5000, self._save_periodic)

    def _build_ui(self):
        self.page_host = tk.Frame(self.root)
        self.page_host.pack(fill="both", expand=True)

        self.timer_page = tk.Frame(self.page_host)
        self.stats_page = tk.Frame(self.page_host)
        for page in (self.timer_page, self.stats_page):
            page.place(relx=0, rely=0, relwidth=1, relheight=1)

        self._build_timer_page()
        self._build_stats_page()
        self._show_page("timer")

    def _build_timer_page(self):
        page = self.timer_page
        self.status = tk.Label(page, text="사용 중", font=("Malgun Gothic", 9, "bold"))
        self.status.pack(pady=(12, 2))

        self.character = tk.Label(page, bd=0)
        self.character.pack(pady=(2, 6))

        timer_row = tk.Frame(page)
        timer_row.pack(pady=(0, 6))
        left = tk.Frame(timer_row)
        left.pack(side="left", padx=18)
        right = tk.Frame(timer_row)
        right.pack(side="left", padx=18)

        tk.Label(left, text="현재 연속 사용", font=("Malgun Gothic", 8)).pack()
        self.cont = tk.Label(left, text="0초", font=("Malgun Gothic", 18, "bold"))
        self.cont.pack()
        tk.Label(right, text="다음 휴식까지", font=("Malgun Gothic", 8)).pack()
        self.remain = tk.Label(right, text="60분", font=("Malgun Gothic", 18, "bold"))
        self.remain.pack()

        self.speech = tk.Label(page, text=pick("playful"), wraplength=410, font=("Malgun Gothic", 9))
        self.speech.pack(padx=20, pady=(6, 8))

        buttons = tk.Frame(page)
        buttons.pack(pady=8)
        self.away_btn = tk.Button(buttons, text="자리비움", command=self.toggle_manual_away)
        self.away_btn.pack(side="left", padx=5)
        tk.Button(buttons, text="오늘 기록", command=self.show_stats).pack(side="left", padx=5)

    def _build_stats_page(self):
        page = self.stats_page
        tk.Label(page, text="오늘 기록", font=("Malgun Gothic", 12, "bold")).pack(pady=(14, 4))
        self.stats_character = tk.Label(page, bd=0)
        self.stats_character.pack(pady=(2, 8))

        grid = tk.Frame(page)
        grid.pack(padx=28, pady=(2, 6), fill="x")
        self.stats_values = {}
        rows = [
            ("active", "실사용"),
            ("away", "자리비움"),
            ("count", "자리비움 횟수"),
            ("longest", "최장 연속 사용"),
            ("ratio", "실사용률"),
        ]
        for idx, (key, label) in enumerate(rows):
            tk.Label(grid, text=label, anchor="w", font=("Malgun Gothic", 9)).grid(row=idx, column=0, sticky="w", pady=4)
            value = tk.Label(grid, text="-", anchor="e", font=("Malgun Gothic", 10, "bold"))
            value.grid(row=idx, column=1, sticky="e", pady=4)
            self.stats_values[key] = value
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_columnconfigure(1, weight=1)

        self.stats_speech = tk.Label(page, text=pick("stats"), wraplength=400, font=("Malgun Gothic", 9))
        self.stats_speech.pack(padx=20, pady=(8, 8))
        tk.Button(page, text="타이머로 돌아가기", command=lambda: self._show_page("timer")).pack(pady=8)

    def _show_page(self, name: str):
        self.current_page = name
        if name == "stats":
            self._update_stats_page()
            self.stats_page.tkraise()
        else:
            self.timer_page.tkraise()

    def _fallback_character(self):
        img = Image.new("RGB", (230, 300), "white")
        draw = ImageDraw.Draw(img)
        draw.ellipse((65, 34, 165, 134), outline="black", width=2)
        draw.text((103, 150), "K", fill="black")
        return img

    def _load_character_image(self, role: str, max_size=(230, 300)):
        path = resolve_asset(role)
        image = Image.open(path).convert("RGB") if path else self._fallback_character()
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        return image

    def _set_character(self, role: str):
        if role == self.character_role:
            return
        try:
            image = self._load_character_image(role)
            self.character_photo = ImageTk.PhotoImage(image)
            self.character.configure(image=self.character_photo)
            self.character_role = role
        except Exception:
            log.exception("character asset failed: %s", role)

    def _set_stats_character(self):
        try:
            image = self._load_character_image("cheer", (230, 260))
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
        mode = classify_workday(datetime.now(), self.state.daily.active_seconds).mode
        if not should_encourage_more_work(mode):
            self.break_gate.reset()
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
            if self.break_gate.should_show(result.break_due, now):
                mode = classify_workday(datetime.now(), self.state.daily.active_seconds).mode
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
        state = classify_workday(datetime.now(), self.state.daily.active_seconds)
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

    def _update_ui(self):
        s = self.state.session
        self.status.configure(text="자리비움" if s.is_away else "사용 중")
        self.away_btn.configure(text="복귀" if s.is_away else "자리비움")
        self.cont.configure(text=fmt(s.continuous_seconds))
        self.remain.configure(text=fmt(self.engine.remaining_to_break()))

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

    def show_toast(self, text):
        self._destroy_toast()
        win = tk.Toplevel(self.root)
        self.toast = win
        win.attributes("-topmost", True)
        win.geometry("380x110")
        tk.Label(win, text="경희 비서", font=("Malgun Gothic", 9, "bold")).pack(pady=(10, 4))
        tk.Label(win, text=text, wraplength=340, font=("Malgun Gothic", 9)).pack(padx=12)
        win.after(8000, lambda w=win: self._destroy_specific(w))

    def show_break_toast(self, text, allow_snooze=True):
        self._destroy_toast()
        win = tk.Toplevel(self.root)
        self.toast = win
        win.attributes("-topmost", True)
        win.geometry("400x150")
        tk.Label(win, text=text, wraplength=350, font=("Malgun Gothic", 10, "bold")).pack(pady=15)
        row = tk.Frame(win)
        row.pack()
        tk.Button(row, text="알았어, 쉴게", command=self.accept_break).pack(side="left", padx=6)
        if allow_snooze:
            tk.Button(row, text="5분 더", command=self.snooze_break).pack(side="left", padx=6)

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
                canvas = Image.new("RGB", (64, 64), "white")
                canvas.paste(image, ((64 - image.width) // 2, (64 - image.height) // 2))
                return canvas
        except Exception:
            log.exception("tray asset failed")
        icon = Image.new("RGB", (64, 64), "white")
        draw = ImageDraw.Draw(icon)
        draw.ellipse((7, 7, 57, 57), outline="black", width=3)
        draw.text((20, 19), "K", fill="black")
        return icon

    def _start_tray(self):
        icon = self._make_tray_icon()
        menu = pystray.Menu(
            item("열기", lambda: self._tray_call(self.show), default=True),
            item("자리비움/복귀", lambda: self._tray_call(self.toggle_manual_away)),
            item("오늘 기록", lambda: self._tray_call(self.show_stats)),
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
