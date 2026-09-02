from __future__ import annotations
import ctypes
import logging
from logging.handlers import RotatingFileHandler
import os
import queue
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
import tkinter as tk
from PIL import Image
import pystray
from pystray import MenuItem as item

from messages import pick
from settings import WORKDAY
from state import load_state, save_state, rollover_daily, reset_untracked_session
from timer_engine import TimerEngine

APP_NAME = "경희 비서"
BREAK_REMIND_SEC = 5 * 60

DATA_DIR = Path(os.getenv("APPDATA", Path.home())) / "KyungheeAssistant"
DATA_DIR.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "state.json"
LOG_FILE = DATA_DIR / "kyunghee.log"

log = logging.getLogger("kyunghee")
log.setLevel(logging.INFO)
if not log.handlers:
    h = RotatingFileHandler(LOG_FILE, maxBytes=2*1024*1024, backupCount=3, encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(h)

def fmt(sec: float) -> str:
    sec = max(0, int(sec)); h, r = divmod(sec, 3600); m, s = divmod(r, 60)
    if h: return f"{h}시간 {m}분"
    if m: return f"{m}분 {s}초"
    return f"{s}초"

def work_mode(now: datetime, active_seconds: float) -> str:
    t = now.time()
    if active_seconds >= WORKDAY.hard_active_limit_sec: return "hard_stop"
    if t >= WORKDAY.late_leave: return "late_leave"
    if t >= WORKDAY.strong_leave: return "strong_leave"
    if t >= WORKDAY.leave_mode: return "leave"
    if t >= WORKDAY.wind_down: return "wind_down"
    return "normal"

class SingleInstance:
    def __init__(self): self.handle = None
    def acquire(self) -> bool:
        if os.name != "nt": return True
        k32 = ctypes.windll.kernel32
        self.handle = k32.CreateMutexW(None, False, "Local\\KyungheeAssistantSingleton")
        return k32.GetLastError() != 183

class App:
    def __init__(self):
        self.state = load_state(STATE_FILE)
        rollover_daily(self.state)
        reset_untracked_session(self.state, time.time())
        self.engine = TimerEngine(self.state)
        self.root = tk.Tk()
        self.root.title(APP_NAME)
        self.root.geometry("470x360")
        self.root.protocol("WM_DELETE_WINDOW", self.root.withdraw)
        self.ui_commands: queue.Queue = queue.Queue()
        self.toast = None
        self.toast_break_active = False
        self.break_toast_shown_at = 0.0
        self.tray_icon = None
        self._build_ui()
        self._start_tray()
        self.root.after(250, self._drain_ui_queue)
        self.root.after(1000, self._tick_safe)
        self.root.after(15000, self._save_periodic)

    def _build_ui(self):
        self.status = tk.Label(self.root, text="사용 중", font=("Malgun Gothic", 9, "bold"))
        self.status.pack(pady=(18, 4))
        tk.Label(self.root, text="현재 연속 사용", font=("Malgun Gothic", 9)).pack()
        self.cont = tk.Label(self.root, text="0초", font=("Malgun Gothic", 24, "bold"))
        self.cont.pack(pady=(0, 12))
        tk.Label(self.root, text="다음 휴식까지", font=("Malgun Gothic", 9)).pack()
        self.remain = tk.Label(self.root, text="60분", font=("Malgun Gothic", 20, "bold"))
        self.remain.pack(pady=(0, 14))
        self.speech = tk.Label(self.root, text=pick("playful"), wraplength=400, font=("Malgun Gothic", 9))
        self.speech.pack(pady=8)
        buttons = tk.Frame(self.root); buttons.pack(pady=12)
        self.away_btn = tk.Button(buttons, text="자리비움", command=self.toggle_manual_away)
        self.away_btn.pack(side="left", padx=5)
        tk.Button(buttons, text="오늘 기록", command=self.show_stats).pack(side="left", padx=5)

    def toggle_manual_away(self):
        if self.state.session.manual_away:
            self.engine.stop_manual_away()
            self.toast_break_active = False
            self.show_toast("복귀했네. 다시 시작할게.")
        else:
            self.engine.start_manual_away()
            self.show_toast(pick("away_start"))
        self._update_ui()

    def accept_break(self):
        self.toast_break_active = False
        self._destroy_toast()
        self.engine.accept_break()
        self.show_toast("좋아. 잠깐 쉬고 와. 시간은 내가 멈춰둘게.")

    def snooze_break(self):
        self.toast_break_active = False
        self._destroy_toast()
        self.engine.snooze_break()
        n = self.state.session.ignored_breaks
        self.show_toast(pick("snooze1" if n == 1 else "snooze2"))

    def _tick_safe(self):
        try:
            rollover_daily(self.state)
            result = self.engine.tick()
            if result.became_active:
                self.toast_break_active = False
                self.show_toast(pick("return", away=fmt(result.away_duration)))
            if result.break_due:
                now = time.monotonic()
                if not self.toast_break_active:
                    self.toast_break_active = True
                    self.break_toast_shown_at = now
                    self.show_break_toast(pick("break"))
                elif now - self.break_toast_shown_at >= BREAK_REMIND_SEC:
                    self.toast_break_active = False
            self._update_ui()
            self._update_workday_message()
        except Exception:
            log.exception("tick failed")
        finally:
            if self.root.winfo_exists(): self.root.after(1000, self._tick_safe)

    def _update_workday_message(self):
        mode = work_mode(datetime.now(), self.state.daily.active_seconds)
        msg = {
            "wind_down": "슬슬 오늘 할 일 정리할 시간이야.",
            "leave": "5시 반이네. 이제 퇴근 모드로 갈게. 하던 것만 마무리하자.",
            "strong_leave": "이제 퇴근할 시간이야. 새 일 벌이지 말고 정리하자.",
            "late_leave": "6시 반 넘었어. 오늘 일은 여기서 닫자.",
            "hard_stop": "오늘 실사용 9시간이야. 이제는 진짜 끝내자.",
        }.get(mode)
        if msg: self.speech.configure(text=msg)

    def _update_ui(self):
        s = self.state.session
        self.status.configure(text="자리비움" if s.is_away else "사용 중")
        self.away_btn.configure(text="복귀" if s.is_away else "자리비움")
        self.cont.configure(text=fmt(s.continuous_seconds))
        self.remain.configure(text=fmt(self.engine.remaining_to_break()))

    def show_stats(self):
        d = self.state.daily
        total = d.active_seconds + d.away_seconds
        ratio = d.active_seconds / total * 100 if total else 0
        self.show_toast(f"오늘 실사용 {fmt(d.active_seconds)} / 자리비움 {fmt(d.away_seconds)} / 실사용률 {ratio:.0f}%")

    def _destroy_specific(self, win):
        try:
            if win is not None and win.winfo_exists(): win.destroy()
        except Exception: pass
        if self.toast is win: self.toast = None

    def _destroy_toast(self): self._destroy_specific(self.toast)

    def show_toast(self, text):
        self._destroy_toast()
        win = tk.Toplevel(self.root); self.toast = win
        win.attributes("-topmost", True); win.geometry("380x110")
        tk.Label(win, text="경희 비서", font=("Malgun Gothic", 9, "bold")).pack(pady=(10, 4))
        tk.Label(win, text=text, wraplength=340, font=("Malgun Gothic", 9)).pack(padx=12)
        win.after(8000, lambda w=win: self._destroy_specific(w))

    def show_break_toast(self, text):
        self._destroy_toast()
        win = tk.Toplevel(self.root); self.toast = win
        win.attributes("-topmost", True); win.geometry("400x150")
        tk.Label(win, text=text, wraplength=350, font=("Malgun Gothic", 10, "bold")).pack(pady=15)
        row = tk.Frame(win); row.pack()
        tk.Button(row, text="알았어, 쉴게", command=self.accept_break).pack(side="left", padx=6)
        tk.Button(row, text="5분 더", command=self.snooze_break).pack(side="left", padx=6)

    def _save_periodic(self):
        try: save_state(STATE_FILE, self.state)
        except Exception: log.exception("save failed")
        finally:
            if self.root.winfo_exists(): self.root.after(15000, self._save_periodic)

    def _drain_ui_queue(self):
        try:
            while True: self.ui_commands.get_nowait()()
        except queue.Empty: pass
        if self.root.winfo_exists(): self.root.after(250, self._drain_ui_queue)

    def _tray_call(self, fn): self.ui_commands.put(fn)

    def _start_tray(self):
        icon = Image.new("RGB", (64, 64), "white")
        menu = pystray.Menu(
            item("열기", lambda: self._tray_call(self.show), default=True),
            item("자리비움/복귀", lambda: self._tray_call(self.toggle_manual_away)),
            item("오늘 기록", lambda: self._tray_call(self.show_stats)),
            item("종료", lambda: self._tray_call(self.quit)),
        )
        self.tray_icon = pystray.Icon("kyunghee_assistant", icon, APP_NAME, menu)
        def run_tray():
            try: self.tray_icon.run()
            except Exception: log.exception("tray failed")
        threading.Thread(target=run_tray, daemon=True).start()

    def show(self): self.root.deiconify(); self.root.lift()
    def quit(self):
        try: save_state(STATE_FILE, self.state)
        except Exception: log.exception("final save failed")
        if self.tray_icon:
            try: self.tray_icon.stop()
            except Exception: pass
        self.root.destroy()
    def run(self): self.root.mainloop()

if __name__ == "__main__":
    singleton = SingleInstance()
    if not singleton.acquire(): raise SystemExit(0)
    if os.name != "nt": raise SystemExit("Windows only")
    App().run()
