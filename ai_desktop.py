"""Optional AI UI adapter; timer/state and local dialogue stay authoritative."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime
import time
import tkinter as tk
from tkinter import filedialog

import app as core
from ai_credentials import AICredentials
from ai_dialogue import AIService, HTTPClient, error_message
from ai_settings_ui import AISettingsPanel
from asset_pack_import import import_numbered_pack
from font_support import ui_font
from messages import pick


CHAT_REPLY_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class PendingChat:
    event: str
    user_text: str
    token: tuple
    deadline: float


def timer_context(state, mode: str, personality: str, now: datetime, **recent) -> dict:
    """An explicit, small snapshot, never a serialized settings/state object."""
    hour = now.hour
    period = ("late" if hour < 6 or hour >= 22 else "morning" if hour < 11 else
              "lunch" if hour < 14 else "afternoon" if hour < 18 else "evening")
    return {
        "day": state.daily.day,
        "local_time": now.strftime("%H:%M"),
        "time_of_day": period,
        "personality": personality,
        "status": "away" if state.session.is_away else "active",
        "active_minutes": int(max(0, state.daily.active_seconds) // 60),
        "continuous_minutes": int(max(0, state.session.continuous_seconds) // 60),
        "away_minutes": int(max(0, state.daily.away_seconds) // 60),
        "away_count": state.daily.away_count,
        "workday_stage": "working" if mode == "normal" else mode,
        **{key: value for key, value in recent.items() if key in {
            "recent_break_minutes", "recent_away_minutes", "seconds_since_return"}},
    }


def local_chat_reply(text: str, personality: str) -> str:
    """Small local conversation fallback, using the existing dialogue engine."""
    if any(word in text for word in ("피곤", "힘들", "지쳤", "졸려", "쉬고", "쉬어", "쉬자", "쉴", "휴식")):
        return pick("break", personality=personality)
    if any(word in text for word in ("퇴근", "마무리", "끝났", "끝냈")):
        return pick("leave", personality=personality)
    if any(word in text for word in ("돌아왔", "복귀", "다녀왔")):
        return pick("return", personality=personality)
    if any(word in text for word in ("고마", "좋아", "응", "알겠")):
        return "응, 여기 있을게. 무리하지 말고 같이 천천히 해보자."
    return pick("playful", personality=personality)


class OptionalAIDesktopMixin:
    """Adds AI to the actual gallery entrypoint without replacing its handlers."""

    def __init__(self):
        self.ai_service = AIService()
        self.ai_credentials = AICredentials(core.DATA_DIR)
        self._ai_loaded_credentials = False
        self._ai_ready = False
        self._ai_closed = False
        self._ai_revision = 0
        self._ai_config = None
        self._ai_seen_mode = None
        self._ai_seen_away = None
        self._ai_seen_day = None
        self._ai_long_bucket = 0
        self._ai_away_since = None
        self._ai_break_since = None
        self._ai_recent_away = 0
        self._ai_recent_break = 0
        self._ai_returned_at = None
        self._chat_window = None
        self._chat_messages = deque(maxlen=12)
        self._chat_ai_note = ""
        self._chat_pending: PendingChat | None = None
        super().__init__()
        self._ai_sync_config()
        self._ai_seen_mode = self._current_workday_state().mode
        self._ai_seen_away = self.state.session.is_away
        self._ai_seen_day = self.state.daily.day
        self._ai_long_bucket = int(self.state.session.continuous_seconds // 3600)
        if self.state.session.is_away:
            self._ai_away_since = time.monotonic()
        self.ai_service.note_local(self.speech.cget("text"))
        self._ai_ready = True
        self.root.after(100, self._ai_poll)

    def _build_timer_page(self):
        super()._build_timer_page()
        self.chat_control = tk.Label(
            self.hero, text="대화", font=ui_font(self.root, 10, role="controls"),
            fg=core.MUTED, bg=self.TRANSPARENT_KEY, cursor="hand2", bd=0,
        )
        self.chat_control.place(x=82, y=14, anchor="nw")
        self.chat_control.bind("<Button-1>", self._open_chat)

    def _build_settings_page(self):
        super()._build_settings_page()
        if not self._ai_loaded_credentials:
            self.ai_credentials.load_saved_key(self.preferences.ai_remember_key)
            self._ai_loaded_credentials = True
        self.ai_settings_panel = AISettingsPanel(
            self.settings_content, self.preferences, self.ai_credentials,
            on_apply=self._apply_ai_settings,
            test_connection=HTTPClient().test_connection,
            font_family=ui_font(self.root)[0],
            theme={"bg": core.PANEL, "input": core.PANEL_2, "text": core.TEXT,
                   "muted": core.MUTED, "accent": core.PURPLE, "good": core.GREEN,
                   "warning": core.AMBER},
        )
        self.ai_settings_panel.pack(fill="x", padx=14, pady=(12, 18))
        pack_row = tk.Frame(self.settings_content, bg=core.PANEL)
        pack_row.pack(fill="x", padx=14, pady=(0, 14))
        self._button(pack_row, "추가 세트 ZIP 가져오기", self._import_asset_pack).pack(anchor="w")
        self._pack_status = self._label(pack_row,
            "default.png 등 10개 역할이 모두 있으면 번호 없이 가져올 수 있고, 새 번호는 자동 배정합니다. 기존 이미지와 원본 ZIP은 보존합니다.",
            size=9, fg=core.MUTED, bg=core.PANEL, wraplength=440, justify="left")
        self._pack_status.pack(fill="x", pady=(5, 0))

    def _import_asset_pack(self):
        selected = filedialog.askopenfilename(parent=self.root, title="추가 이미지 세트 ZIP",
                                               filetypes=[("ZIP", "*.zip")])
        if not selected:
            return
        from pathlib import Path
        from asset_manager import ASSET_DIR
        try:
            result = import_numbered_pack(Path(selected), ASSET_DIR)
        except Exception as exc:
            # Never display ZIP-controlled exception text or paths.
            message = str(exc) if isinstance(exc, ValueError) else "가져오지 못했습니다. ZIP 형식과 폴더 쓰기 권한을 확인해 주세요."
            self._pack_status.configure(text=message, fg=core.AMBER)
            return
        details = [f"세트 {', '.join(result.sets)} · {result.added}장 추가, 동일 파일 {result.identical}장 유지."]
        if result.auto_assigned:
            details.append(f"번호 없는 세트에 {', '.join(result.auto_assigned)}번을 자동 배정했습니다.")
        if result.reused:
            if result.added:
                details.append(f"동일한 내용의 세트는 {', '.join(result.reused)}번으로 합쳤습니다.")
            else:
                details.append(f"동일한 세트가 있어 기존 {', '.join(result.reused)}번을 그대로 사용합니다.")
        if result.added:
            details.append("앱을 다시 열면 세트 목록에 반영됩니다.")
        self._pack_status.configure(text=" ".join(details), fg=core.GREEN)

    def _apply_ai_settings(self, enabled, remember, _api_key):
        candidate = replace(self.preferences, ai_enabled=enabled, ai_remember_key=remember)
        # Privacy actions must take effect even if the ordinary settings file is
        # read-only. In particular, clearing a key cannot leave the worker's old
        # credential or an already queued response active.
        self._ai_invalidate()
        self.ai_service.configure(enabled, self.ai_credentials.api_key)
        self._ai_config = (enabled, self.ai_credentials.api_key)
        try:
            self.apply_preferences(candidate)
        except Exception:
            self.preferences = candidate
            self._refresh_chat()
            raise

    def apply_preferences(self, preferences):
        previous_personality = self.preferences.personality
        super().apply_preferences(preferences)
        if previous_personality != preferences.personality:
            self._ai_invalidate()
        self._ai_sync_config()
        if hasattr(self, "ai_settings_panel"):
            self.ai_settings_panel.refresh(preferences)
        self._refresh_chat()

    def _ai_sync_config(self):
        config = (self.preferences.ai_enabled, self.ai_credentials.api_key)
        if config != self._ai_config:
            self._ai_invalidate()
            self.ai_service.configure(*config)
            self._ai_config = config

    def _ai_invalidate(self):
        self._ai_revision += 1
        self.ai_service.invalidate()
        self._cancel_pending_chat()

    def _cancel_pending_chat(self):
        if self._chat_pending is None:
            return
        self._chat_pending = None
        self._chat_ai_note = "상태가 바뀌어 답변 대기를 취소했어요. 다시 말해 주세요."
        if self._chat_messages and self._chat_messages[-1][0] == "승아 · 대기 중":
            self._chat_messages[-1] = ("승아 · 안내", self._chat_ai_note)
        self._refresh_chat()

    def _ai_token(self):
        return (self._ai_revision, self.state.daily.day, self.state.session.is_away,
                self._current_workday_state().mode, self.preferences.personality)

    def _ai_context(self):
        now_mono = time.monotonic()
        if not self.state.session.is_away and self._ai_away_since is not None:
            self._ai_recent_away = int(max(0, now_mono - self._ai_away_since) // 60)
            if self._ai_break_since is not None:
                self._ai_recent_break = int(max(0, now_mono - self._ai_break_since) // 60)
            self._ai_away_since = self._ai_break_since = None
            self._ai_returned_at = now_mono
        recent = {"recent_away_minutes": self._ai_recent_away,
                  "recent_break_minutes": self._ai_recent_break}
        if self._ai_returned_at is not None:
            recent["seconds_since_return"] = int(now_mono - self._ai_returned_at)
        return timer_context(self.state, self._current_workday_state().mode,
                             self.preferences.personality, datetime.now(), **recent)

    def _request_ai(self, event, user_text=""):
        if not self._ai_ready or self._ai_closed:
            return False
        return self.ai_service.request(event, self._ai_context(), user_text=user_text,
                                       token=self._ai_token())

    def _say(self, kind, text=None, work_mode="normal"):
        super()._say(kind, text, work_mode)
        if not self._ai_ready:
            return
        self._ai_invalidate()
        self.ai_service.note_local(self.speech.cget("text"))
        self._apply_widget_appearance()
        if kind == "return":
            self._request_ai("return")
        elif kind in {"wind_down", "leave", "strong_leave", "late_leave", "hard_stop"}:
            if kind != self._ai_seen_mode:
                self._ai_seen_mode = kind
                self._request_ai("workday" if kind == "wind_down" else "leave")

    def _cycle_message(self, event=None):
        self._ai_invalidate()
        result = super()._cycle_message(event)
        self.ai_service.note_local(self.speech.cget("text"))
        return result

    def show_break_toast(self, text, allow_snooze=True):
        super().show_break_toast(text, allow_snooze)
        if self._ai_ready and not self._break_notifications_suppressed():
            self._ai_invalidate()
            self.speech.configure(text=text)
            self.ai_service.note_local(text)
            self._apply_widget_appearance()
            self._request_ai("break")

    def accept_break(self):
        super().accept_break()
        self._ai_break_since = self._ai_away_since = time.monotonic()
        self._request_ai("break")

    def snooze_break(self):
        super().snooze_break()
        self._request_ai("break")

    def _update_ui(self):
        super()._update_ui()
        if not self._ai_ready:
            return
        day = self.state.daily.day
        away = self.state.session.is_away
        if day != self._ai_seen_day:
            self._ai_invalidate()
            self._ai_seen_day = day
            self._ai_recent_away = self._ai_recent_break = 0
            self._ai_returned_at = None
            self._chat_messages.clear()
            self._chat_ai_note = ""
            self._refresh_chat()
        if self._current_workday_state().mode == "normal":
            self._ai_seen_mode = "normal"
        if away != self._ai_seen_away:
            # Return dialogue can already have submitted a valid request in _say.
            if away:
                self._ai_invalidate()
                self._ai_away_since = time.monotonic()
            self._ai_seen_away = away
        bucket = int(self.state.session.continuous_seconds // 3600)
        if bucket != self._ai_long_bucket:
            self._ai_long_bucket = bucket
            if bucket >= 2 and not away:
                self._request_ai("long_use")

    def _ai_poll(self):
        if self._ai_closed:
            return
        if self._chat_pending is not None and self._chat_pending.token != self._ai_token():
            self._cancel_pending_chat()
        for result in self.ai_service.poll(token=self._ai_token()):
            if result.token != self._ai_token():
                continue
            if result.event in {"chat", "daily_close"}:
                pending = self._chat_pending
                if pending is None or pending.token != result.token or pending.event != result.event:
                    continue
                if time.monotonic() >= pending.deadline:
                    self._fallback_pending_chat("timeout")
                elif result.text:
                    self._finish_chat_reply(result.text, "AI", "AI 답변이 도착했어요.")
                else:
                    self._fallback_pending_chat(result.error_code or "invalid_response")
                continue
            if result.text and not self._break_notifications_suppressed():
                self.speech.configure(text=result.text)
                self.last_dialogue_at = time.monotonic()
                self._apply_widget_appearance()
            self._refresh_chat()
        # The backend deliberately drops expired or stale results. The UI owns
        # its deadline so a dropped response cannot leave a waiting row forever.
        if self._chat_pending is not None and time.monotonic() >= self._chat_pending.deadline:
            self._fallback_pending_chat("timeout")
        if self.root.winfo_exists():
            self.root.after(100, self._ai_poll)

    def _open_chat(self, _event=None):
        if self._chat_window is not None and self._chat_window.winfo_exists():
            self._chat_window.deiconify()
            self._chat_window.attributes("-topmost", True)
            self._chat_window.lift()
            self._chat_entry.focus_set()
            return "break"
        win = tk.Toplevel(self.root)
        self._chat_window = win
        win.title("승아와 대화")
        win.configure(bg=core.BG)
        win.attributes("-topmost", True)
        win.minsize(340, 360)
        self.root.update_idletasks()
        area = self._best_work_area(self.root.winfo_x(), self.root.winfo_y(), 410, 500)
        left, top, right, bottom = area
        x = min(max(left, self.root.winfo_x() + self.root.winfo_width() + 8), max(left, right - 410))
        y = min(max(top, self.root.winfo_y()), max(top, bottom - 500))
        win.geometry(f"410x500+{x}+{y}")
        tk.Label(win, text="승아와 잠깐 이야기해요", font=ui_font(self.root, 13, role="title"),
                 fg=core.TEXT, bg=core.BG).pack(anchor="w", padx=16, pady=(14, 4))
        self._chat_status = tk.Label(win, text="", font=ui_font(self.root, 9),
                                     fg=core.MUTED, bg=core.BG, wraplength=375, justify="left")
        self._chat_status.pack(fill="x", padx=16, pady=(0, 8))
        history_frame = tk.Frame(win, bg=core.PANEL)
        history_frame.pack(fill="both", expand=True, padx=12)
        scroll = tk.Scrollbar(history_frame)
        scroll.pack(side="right", fill="y")
        self._chat_history = tk.Text(history_frame, bg=core.PANEL, fg=core.TEXT,
            font=ui_font(self.root, 11), wrap="word", spacing1=4, spacing3=10,
            relief="flat", padx=12, pady=10, height=1, width=1,
            state="disabled", yscrollcommand=scroll.set)
        self._chat_history.pack(fill="both", expand=True)
        scroll.configure(command=self._chat_history.yview)
        self._chat_history.tag_configure("user", foreground=core.MUTED)
        self._chat_history.tag_configure("speaker", foreground=core.GREEN)
        row = tk.Frame(win, bg=core.BG)
        row.pack(fill="x", padx=12, pady=10)
        self._chat_entry = tk.Entry(row, font=ui_font(self.root, 11), bg=core.PANEL_2,
            fg=core.TEXT, insertbackground=core.TEXT, relief="flat")
        self._chat_entry.pack(side="left", fill="x", expand=True, ipady=8)
        self._chat_entry.bind("<Return>", self._send_chat)
        self._button(row, "보내기", self._send_chat, primary=True).pack(side="left", padx=(8, 0))
        footer = tk.Frame(win, bg=core.BG)
        footer.pack(fill="x", padx=12, pady=(0, 12))
        self._button(footer, "오늘 마무리", self._daily_close).pack(side="left")
        self._button(footer, "대화 지우기", self._clear_chat).pack(side="right")
        win.bind("<Escape>", lambda _e: win.withdraw())
        win.protocol("WM_DELETE_WINDOW", win.withdraw)
        self._refresh_chat()
        self._chat_entry.focus_set()
        return "break"

    def _send_chat(self, _event=None):
        text = self._chat_entry.get().strip()
        if not text:
            return "break"
        if len(text) > 400:
            self._chat_status.configure(text="짧게 400자 이내로 이야기해 주세요.")
            return "break"
        if self._start_chat_reply("chat", text):
            self._chat_entry.delete(0, "end")
        return "break"

    def _daily_close(self):
        self._start_chat_reply("daily_close", "오늘 하루 마무리하자.")

    def _start_chat_reply(self, event, text):
        if self._chat_pending is not None:
            self._chat_ai_note = "답변을 기다리고 있어요. 답변이 도착하면 다음 말을 보내 주세요."
            self._refresh_chat()
            return False
        self._ai_invalidate()
        enabled = self.preferences.ai_enabled and bool(self.ai_credentials.api_key)
        if enabled and not self._request_ai(event, user_text=text if event == "chat" else ""):
            self._chat_ai_note = "지금은 AI 요청을 시작할 수 없어요. 잠시 후 다시 보내 주세요."
            self._refresh_chat()
            return False
        self._chat_messages.extend((("나", text), ("승아 · 대기 중", "답변을 생각하고 있어요…")))
        self._chat_pending = PendingChat(event, text, self._ai_token(),
                                         time.monotonic() + CHAT_REPLY_TIMEOUT_SECONDS)
        # Prevent periodic idle dialogue from replacing the existing speech
        # while this explicit chat is waiting. Timer and meaningful events run on.
        self.last_dialogue_at = time.monotonic()
        if enabled:
            self._chat_ai_note = "AI 답변을 기다리고 있어요."
        else:
            self._fallback_pending_chat()
        self._refresh_chat()
        return True

    def _finish_chat_reply(self, text, source, note):
        self._chat_pending = None
        if self._chat_messages and self._chat_messages[-1][0] == "승아 · 대기 중":
            self._chat_messages[-1] = (f"승아 · {source}", text)
        # Explicit chat still completes in its window during fullscreen mode;
        # the timer overlay continues to respect presentation suppression.
        if not self._break_notifications_suppressed():
            self.speech.configure(text=text)
            self._apply_widget_appearance()
        self.last_dialogue_at = time.monotonic()
        self._chat_ai_note = note
        self._refresh_chat()

    def _fallback_pending_chat(self, error_code=""):
        pending = self._chat_pending
        if pending is None:
            return
        self._chat_pending = None
        self._ai_invalidate()
        reply = (pick("leave", personality=self.preferences.personality) if pending.event == "daily_close"
                 else local_chat_reply(pending.user_text, self.preferences.personality))
        self.ai_service.note_local(reply)
        self._finish_chat_reply(reply, "로컬", error_message(error_code) if error_code else "로컬 대사로 답했어요.")

    def _clear_chat(self):
        self._ai_invalidate()
        self._chat_messages.clear()
        self._chat_ai_note = ""
        # Configuration changes clear the service's day/chat memory as well.
        self.ai_service.configure(False, "")
        self._ai_config = None
        self._ai_sync_config()
        self._refresh_chat()

    def _refresh_chat(self):
        if self._chat_window is None or not self._chat_window.winfo_exists():
            return
        enabled = self.preferences.ai_enabled and bool(self.ai_credentials.api_key)
        self._chat_status.configure(text=(
            "AI 사용 중 · 필요한 타이머 정보와 보낸 대화가 OpenAI로 전송됩니다. AI 답변을 기다려요."
            if enabled else "로컬 대화 중 · AI 설정에서 API를 켜면 더 자연스럽게 답해요. 최근 대화는 앱을 닫으면 사라져요.")
            + ("\n" + self._chat_ai_note if self._chat_ai_note else ""))
        self._chat_history.configure(state="normal")
        self._chat_history.delete("1.0", "end")
        if not self._chat_messages:
            self._chat_history.insert("end", "승아에게 짧게 말을 걸어보세요.\n대화는 타이머 동작을 바꾸지 않아요.")
        for speaker, text in self._chat_messages:
            self._chat_history.insert("end", speaker + "\n", "user" if speaker == "나" else "speaker")
            self._chat_history.insert("end", text + "\n\n")
        self._chat_history.configure(state="disabled")
        self._chat_history.see("end")
        self._chat_window.attributes("-topmost", True)

    def quit(self):
        self._ai_closed = True
        self._chat_pending = None
        self.ai_service.close()
        super().quit()
