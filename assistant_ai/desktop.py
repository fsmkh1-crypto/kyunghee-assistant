from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from datetime import date, datetime
import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox

import app as core

from .service import AssistantService
from .timer_tools import TimerTools, validate_arguments
from .ui import AssistantWindows
from .windows_speech_hitbox import SpeechHitbox


_PROACTIVE_MIN_SPACING = 15
_PERIODIC_MIN_SPACING = 5 * 60
_PROACTIVE_MAX_AGE = 25
_TOOL_TIMEOUT = 120
_CHAT_REPLY_SECONDS = 22
_CHAT_EXPAND_SECONDS = 90
_CHAT_PREVIEW_LINES = 3
_CHAT_ROLE = {"composing": "rest", "waiting": "rest", "reply": "default", "error": "worry"}
_CHAT_LABEL = {"composing": "듣는 중", "waiting": "생각 중", "reply": "답변", "error": "응답 오류"}
_CHAT_LINES = {
    "composing": "오빠, 듣고 있어요.",
    "waiting": "잠깐만요, 생각하고 있어요.",
    "error": "답을 가져오지 못했어요. 대화창에서 확인해 주세요.",
}


@dataclass
class _ProactiveRequest:
    event: str
    context: dict
    started_at: float
    last_dialogue_at: float
    revision: int
    toast: tk.Toplevel | None
    cancel: threading.Event


def _failure(message):
    return {"ok": False, "error": message, "message": message}


class DesktopAssistantMixin:
    """Attach optional AI without changing the timer engine or its alert gate."""

    def __init__(self):
        self._assistant_service = None
        self._assistant_windows = None
        self._assistant_ui_thread = threading.get_ident()
        self._assistant_shutdown = threading.Event()
        self._assistant_pending = None
        self._assistant_periodic_due = False
        self._assistant_last_attempt = float("-inf")
        self._assistant_last_periodic = float("-inf")
        self._chat_phase = "idle"
        self._expandable_reply = ""
        self._chat_expiry = None
        self._chat_hitbox = None
        self._chat_hitbox_sync = None
        self._timer_character_role = "default"
        self._assistant_recent_dialogue = deque(maxlen=12)
        self._assistant_events = deque(maxlen=40)
        super().__init__()
        self.root.bind("<Control-Shift-A>", self._open_assistant_shortcut, add="+")
        self._assistant_tools = TimerTools(self)
        try:
            self._assistant_service = AssistantService(core.DATA_DIR)
            self._assistant_windows = AssistantWindows(
                self.root, self._assistant_service,
                context=self._assistant_tools.context, dispatch=self._dispatch_assistant_tool,
                on_chat_state=self._show_chat_phase,
                chat_work_area=self._best_work_area,
                image_catalog=lambda: self.image_action_catalog(),
                image_propose=lambda action: self.propose_image_action(action),
                image_apply=lambda proposal_id: self.apply_image_action(proposal_id),
                image_cancel=lambda proposal_id: self.cancel_image_action(proposal_id),
                image_undo=lambda: self.undo_image_action(),
                image_preview=lambda ref: self._decode_asset_ref(ref),
            )
        except Exception:
            self._assistant_service = None
            core.log.warning("AI assistant could not be initialized")

    def _build_timer_page(self):
        super()._build_timer_page()
        button = tk.Button(
            self.hero, text="승아", command=self._open_assistant_chat,
            font=(self.FONT_FAMILY, 9, "bold"), fg=core.TEXT, bg=core.PANEL_2,
            activeforeground=core.TEXT, activebackground=core.PURPLE_2,
            bd=0, relief="flat", cursor="hand2", padx=6,
        )
        # Speech opens chat; keep this state holder unplaced rather than adding
        # a second chat control over the compact timer.
        self._chat_button = button
        self._chat_speech = self._new_speech_bubble("")
        self._chat_speech.bind("<Button-1>", self._activate_chat_reply)
        self._chat_speech.bind("<Button-3>", self._dismiss_chat_reply)
        if os.name == "nt":
            self._chat_hitbox = SpeechHitbox(self.root, self._activate_chat_reply, self._dismiss_chat_reply)
            for event in ("<Configure>", "<Map>", "<Unmap>"):
                self.root.bind(event, self._queue_chat_hitbox_sync, add="+")
            self._chat_speech.bind("<Configure>", self._queue_chat_hitbox_sync, add="+")

    def _visible_speech(self):
        if self._chat_phase != "idle":
            return self._chat_speech
        return super()._visible_speech()

    def _apply_widget_appearance(self):
        super()._apply_widget_appearance()
        self._queue_chat_hitbox_sync()

    def _show_page(self, name):
        super()._show_page(name)
        self._queue_chat_hitbox_sync()

    def _queue_chat_hitbox_sync(self, _event=None):
        if self._chat_hitbox is None or self._assistant_shutdown.is_set():
            return
        if self._chat_hitbox_sync is None:
            self._chat_hitbox_sync = self.root.after_idle(self._sync_chat_hitbox)

    def _sync_chat_hitbox(self):
        self._chat_hitbox_sync = None
        try:
            if (
                self._chat_phase == "reply" and self.current_page == "timer"
                and self._chat_speech.winfo_viewable()
            ):
                self._chat_hitbox.show_over(self._chat_speech)
            else:
                self._chat_hitbox.hide()
        except (OSError, tk.TclError):
            core.log.exception("speech hitbox failed")
            self._chat_hitbox.close()
            self._chat_hitbox = None

    def _set_character(self, role):
        self._timer_character_role = role
        return super()._set_character(_CHAT_ROLE.get(self._chat_phase, role))

    def _say(self, kind, text=None, work_mode="normal"):
        result = super()._say(kind, text, work_mode)
        speech = self.speech.cget("text")
        if speech and (not self._assistant_recent_dialogue or self._assistant_recent_dialogue[-1] != speech):
            self._assistant_recent_dialogue.append(speech)
        return result

    def _cancel_chat_expiry(self):
        if self._chat_expiry is not None:
            self.root.after_cancel(self._chat_expiry)
            self._chat_expiry = None

    def _show_chat_phase(self, phase, text=""):
        self._cancel_chat_expiry()
        if phase == "idle" and self._chat_phase == "idle":
            return
        self._chat_phase = phase
        self._expandable_reply = ""
        if phase == "idle":
            self._chat_button.configure(text="승아")
            self._chat_speech.place_forget()
            super()._set_character(self._timer_character_role)
        else:
            self._cancel_proactive()
            self._chat_button.configure(text=f"승아 {_CHAT_LABEL[phase]}")
            super()._set_character(_CHAT_ROLE[phase])
            if phase == "reply":
                self._render_chat_reply(text)
            else:
                self._chat_speech.configure(text=_CHAT_LINES[phase])
                if phase == "error":
                    self._schedule_chat_expiry()
        self._refresh_chat_layout()

    def _refresh_chat_layout(self):
        self._apply_widget_appearance()
        if self.current_page == "timer":
            self._resize_for_page("timer")

    def _schedule_chat_expiry(self, seconds=_CHAT_REPLY_SECONDS):
        self._cancel_chat_expiry()
        self._chat_expiry = self.root.after(seconds * 1000, self._expire_chat_reply)

    def _expire_chat_reply(self):
        self._chat_expiry = None
        self._show_chat_phase("idle")

    def _render_chat_reply(self, text):
        text = text.strip() or "표시할 답변이 없어요."
        preview = text.split("\n\n웹 조회 시각 ", 1)[0]
        if "https://" in preview or "http://" in preview:
            preview = re.sub(r"\[(\d+)\]\(<https?://[^>]+>\)", r"[\1]", preview)
        lines = self._chat_speech.wrapped_lines(preview, limit=_CHAT_PREVIEW_LINES + 2)
        if len(lines) > _CHAT_PREVIEW_LINES + 1 or "https://" in text or "http://" in text:
            self._expandable_reply = text
            text = "\n".join(lines[:_CHAT_PREVIEW_LINES]).rstrip() + "\n전체 답변 보기 ›"
        self._chat_speech.configure(text=text)
        show_preview = self._expandable_reply and self._effective_display_flag("show_message")
        self._schedule_chat_expiry(_CHAT_EXPAND_SECONDS if show_preview else _CHAT_REPLY_SECONDS)

    def _activate_chat_reply(self, _event=None):
        if self._chat_phase != "reply" or not self._expandable_reply:
            self._open_assistant_chat()
        else:
            self._assistant_windows.open_reply(self._expandable_reply)
            self._show_chat_phase("idle")
        return "break"

    def _dismiss_chat_reply(self, _event=None):
        if self._chat_phase in {"reply", "error"}:
            self._show_chat_phase("idle")
        return "break"

    def _build_header(self, parent, title, back_command=None, settings_command=None):
        row = super()._build_header(parent, title, back_command, settings_command)
        if parent is self.settings_page:
            self._button(row, "승아 AI 설정", self._open_assistant_settings).pack(side="right")
        return row

    def _tray_menu_items(self):
        *existing, quit_item = super()._tray_menu_items()
        return (
            *existing,
            core.item("승아와 대화", lambda: self._tray_call(self._open_assistant_chat)),
            core.item("승아 AI 설정", lambda: self._tray_call(self._open_assistant_settings)),
            quit_item,
        )

    def _open_assistant_chat(self):
        if self._assistant_windows is None:
            self._assistant_unavailable()
            return
        if self.current_page != "timer":
            self._show_page("timer")
        if not self.root.winfo_viewable():
            self.show()
        self._assistant_windows.open_chat()

    def _open_assistant_shortcut(self, _event):
        self._open_assistant_chat()
        return "break"

    def _open_assistant_settings(self):
        if self._assistant_windows is None:
            self._assistant_unavailable()
            return
        self._assistant_windows.open_settings()

    def _assistant_unavailable(self):
        messagebox.showerror("승아 AI", "AI 설정을 열 수 없어요. 타이머는 계속 작동해요.", parent=self.root)

    def _emergency_hide(self, event=None):
        if self._assistant_windows is not None:
            self._assistant_windows.hide()
        self._cancel_proactive()
        return super()._emergency_hide(event)

    def quit(self):
        self._assistant_shutdown.set()
        self._cancel_proactive()
        self._cancel_chat_expiry()
        if self._chat_hitbox_sync is not None:
            self.root.after_cancel(self._chat_hitbox_sync)
        if self._chat_hitbox is not None:
            self._chat_hitbox.close()
        try:
            if self._assistant_windows is not None:
                self._assistant_windows.close()
        finally:
            super().quit()

    def _dispatch_assistant_tool(self, name, arguments, cancel):
        # Only the chat worker calls dispatch. Tk is free to drain this queue and
        # to keep ticking the timer while a local confirmation window is open.
        if threading.get_ident() == self._assistant_ui_thread:
            return _failure("타이머 요청을 처리할 수 없어요.")
        try:
            if name == "save_assistant_memory":
                text = arguments.get("text") if isinstance(arguments, dict) and arguments.keys() == {"text"} else None
                if not isinstance(text, str) or not text.strip() or len(text) > 2000 or "\x00" in text:
                    raise ValueError("기억할 내용을 1~2,000자로 알려줘요.")
                arguments = {"text": text.strip()}
            else:
                arguments = validate_arguments(name, arguments)
        except ValueError as exc:
            return _failure(str(exc))

        finished = threading.Event()
        deadline = time.monotonic() + _TOOL_TIMEOUT
        result = _failure("타이머 요청이 취소됐어요.")

        def cancelled():
            return cancel.is_set() or self._assistant_shutdown.is_set() or time.monotonic() >= deadline

        def run_tool():
            nonlocal result
            try:
                if cancelled():
                    return
                confirm = lambda description: self._confirm_assistant_change(description, cancelled)
                if name == "save_assistant_memory":
                    result = self._save_assistant_memory(arguments["text"], confirm, cancelled)
                elif name == "get_image_catalog":
                    result = {"ok": True, **self.image_action_catalog()}
                elif name == "propose_image_action":
                    action = {key: value for key, value in arguments.items() if value is not None}
                    result = self.propose_image_action(action)
                    result = {**result, "ok": result.get("status") == "pending", "message": result.get("summary", "이미지 변경 제안을 확인해 주세요.")}
                    if result["ok"] and not cancelled():
                        self._assistant_windows.show_image_proposal(result)
                else:
                    result = self._assistant_tools.execute(name, arguments, confirm)
            except Exception:
                core.log.warning("AI timer tool failed: %s", name)
                result = _failure("앱에서 요청을 처리하는 중 문제가 생겼어요.")
            finally:
                finished.set()

        if cancelled():
            return result
        self.ui_commands.put(run_tool)
        while not finished.wait(0.1):
            if cancelled():
                return _failure("타이머 요청이 취소됐거나 확인 시간이 지났어요.")
        return result

    def _save_assistant_memory(self, text, confirm, cancelled):
        service = self._assistant_service
        if not service.load_settings().memory_enabled:
            return _failure("AI 설정에서 대화와 기억의 로컬 저장을 먼저 켜 주세요.")
        if not confirm("이 내용을 기억에 저장해요.\n\n" + text) or cancelled():
            return _failure("확인하지 않아 기억에 저장하지 않았어요.")
        return service.save_assistant_memory(text)

    def _confirm_assistant_change(self, description, cancelled):
        if cancelled():
            return False
        parent = self._assistant_windows.confirmation_parent()
        window = tk.Toplevel(parent, bg=core.BG)
        window.title("승아 요청 확인")
        if parent.winfo_viewable():
            window.transient(parent)
        window.minsize(420, 210)
        window.geometry("480x255")
        self._label(window, "이 요청을 적용할까요?", size=11, weight="bold").pack(anchor="w", padx=14, pady=(12, 6))
        frame = tk.Frame(window, bg=core.BG)
        frame.pack(fill="both", expand=True, padx=14)
        body = tk.Text(frame, wrap="word", font=(self.FONT_FAMILY, 10), fg=core.TEXT, bg=core.PANEL, bd=0, padx=8, pady=7)
        scroll = tk.Scrollbar(frame, command=body.yview)
        body.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        body.pack(side="left", fill="both", expand=True)
        body.insert("1.0", description)
        body.configure(state="disabled")
        controls = tk.Frame(window, bg=core.BG)
        controls.pack(fill="x", padx=14, pady=12)
        approved = False
        poll_id = None

        def close(apply=False):
            nonlocal approved, poll_id
            approved = apply and not cancelled()
            if poll_id is not None:
                window.after_cancel(poll_id)
                poll_id = None
            window.destroy()

        def watch_cancellation():
            nonlocal poll_id
            poll_id = None
            if cancelled():
                close()
            else:
                poll_id = window.after(150, watch_cancellation)

        self._button(controls, "적용", lambda: close(apply=True), primary=True).pack(side="right")
        cancel_button = self._button(controls, "취소", close)
        cancel_button.pack(side="right", padx=(0, 6))
        window.bind("<Escape>", lambda _event: close())
        window.protocol("WM_DELETE_WINDOW", close)
        poll_id = window.after(150, watch_cancellation)
        window.wait_visibility()
        window.grab_set()
        cancel_button.focus_set()
        parent.wait_window(window)
        return approved and not cancelled()

    def _sync_assistant_preference_controls(self, changes):
        controls = {
            **self.settings_bool_vars, **self.settings_time_vars,
            "break_interval_minutes": self.break_interval_var,
            "snooze_minutes": self.snooze_minutes_var,
        }
        for field, value in changes.items():
            controls[field].set(value)

    def toggle_manual_away(self):
        super().toggle_manual_away()
        self._request_proactive("away" if self.state.session.is_away else "return")

    def accept_break(self):
        previous_toast = self.toast
        super().accept_break()
        self._request_proactive("break_started", self.toast if self.toast is not previous_toast else None)

    def _tick_safe(self):
        was_away = self.state.session.is_away
        previous_mode = self.last_work_mode
        previous_alert = self.break_gate.last_shown_at
        previous_toast = self.toast
        self._assistant_periodic_due = False
        super()._tick_safe()
        away = self.state.session.is_away
        if self.break_gate.last_shown_at > previous_alert and self.toast is not previous_toast:
            self._request_proactive("rest", self.toast)
        elif self.last_work_mode != previous_mode and self.last_work_mode != "normal":
            self._request_proactive("leave")
        elif away != was_away:
            if away and self.last_work_mode == "normal":
                self._say("away_start")
            self._request_proactive("away" if away else "return", self.toast if self.toast is not previous_toast else None)
        elif self._assistant_periodic_due:
            self._request_proactive("periodic")

    def _update_dialogue(self):
        # The original local dialogue always appears first, including when the
        # AI is offline, throttled, busy, silent, or waiting on a slow network.
        previous_time, previous_mode = self.last_dialogue_at, self.last_work_mode
        super()._update_dialogue()
        if self.last_dialogue_at != previous_time and previous_mode == self.last_work_mode and self._proactive_enabled():
            self._assistant_periodic_due = True

    def _cycle_message(self, event=None):
        self._open_assistant_chat()

    def _proactive_enabled(self):
        service = self._assistant_service
        return service is not None and service.can_proactively_speak()

    def _cancel_proactive(self):
        if self._assistant_pending is not None:
            self._assistant_pending.cancel.set()
            self._assistant_pending = None

    def _request_proactive(self, event, toast=None):
        service = self._assistant_service
        if event != "periodic":
            self._assistant_events.append({"date": date.today().isoformat(), "time": datetime.now().astimezone().isoformat(timespec="seconds"), "event": event})
        if self._chat_phase != "idle" and toast is None:
            return
        if self._assistant_pending is not None:
            if event != "periodic":
                self._cancel_proactive()
            else:
                return
        if service is None or not service.can_proactively_speak(event) or self._break_notifications_suppressed():
            return
        if toast is None and (not self.preferences.show_message or self.current_page != "timer" or not self.root.winfo_viewable()):
            return
        if self.last_work_mode == "hard_stop":
            return
        now = time.monotonic()
        if now - self._assistant_last_attempt < _PROACTIVE_MIN_SPACING:
            return
        if event == "periodic":
            if now - self._assistant_last_periodic < _PERIODIC_MIN_SPACING:
                return
            self._assistant_last_periodic = now
        request = _ProactiveRequest(
            event, self._assistant_tools.context(), now, self.last_dialogue_at,
            service.revision, toast, threading.Event(),
        )
        self._assistant_pending = request
        self._assistant_last_attempt = now

        def work():
            text = None
            failed = False
            try:
                text = service.proactive(request.event, context=request.context, cancel=request.cancel)
            except Exception:
                failed = True
            if not self._assistant_shutdown.is_set():
                self.ui_commands.put(lambda: self._finish_proactive(request, text, failed))

        threading.Thread(target=work, name="seunga-proactive", daemon=True).start()

    def _finish_proactive(self, request, text, failed):
        if self._assistant_pending is not request:
            return
        self._assistant_pending = None
        service = self._assistant_service
        if (
            self._assistant_shutdown.is_set() or request.cancel.is_set()
            or time.monotonic() - request.started_at > _PROACTIVE_MAX_AGE
            or service is None or service.revision != request.revision or not service.can_proactively_speak()
            or self._break_notifications_suppressed()
        ):
            return
        current = self._assistant_tools.context()
        if any(current[key] != request.context[key] for key in ("date", "is_away", "workday_mode", "break_reminders_enabled_today")):
            return
        if request.toast is not None:
            toast = request.toast
            if text and self.toast is toast and toast.winfo_exists() and hasattr(toast, "body_label"):
                toast.body_label.configure(text=text[:89].rstrip() + "…" if len(text) > 90 else text)
            return
        if (
            self.last_dialogue_at != request.last_dialogue_at or not self.preferences.show_message
            or self.current_page != "timer" or not self.root.winfo_viewable()
        ):
            return
        if text:
            self.speech.configure(text=text)
            self._assistant_recent_dialogue.append(text)
            self.last_dialogue_at = time.monotonic()
            self._apply_widget_appearance()
