from __future__ import annotations

from dataclasses import dataclass
from collections import deque
from datetime import date, datetime
import math
import os
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox

import app as core
from messages import maybe_pick_custom, maybe_pick_daily_temperament, maybe_pick_rare, pick, time_of_day_kind

from .service import AssistantService
from .timer_tools import TimerTools, validate_arguments
from .ui import AssistantWindows
from .windows_speech_hitbox import SpeechHitbox


_PROACTIVE_MIN_SPACING = 60
_RECENT_CHAT_QUIET_SECONDS = 5 * 60
_PROACTIVE_MAX_AGE = 25
_IMPORTANT_EVENT_SECONDS = 60
_TOOL_TIMEOUT = 120
_CHAT_REPLY_SECONDS = 22
_CHAT_PREVIEW_LINES = 3
_CHAT_ROLE = {"composing": "rest", "waiting": "rest", "reply": "default", "error": "worry"}
_CHAT_LABEL = {"composing": "듣는 중", "waiting": "생각 중", "reply": "답변", "error": "응답 오류"}
_CHAT_LINES = {
    "composing": "오빠, 듣고 있어요.",
    "waiting": "잠깐만요, 생각하고 있어요.",
    "error": "답을 가져오지 못했어요. 대화창에서 확인해 주세요.",
}
_LOCAL_DIALOGUE_EVENTS = {
    "break": "rest", "away_start": "away", "return": "return",
    "snooze1": "snooze", "snooze2": "snooze",
    **{mode: "leave" for mode in ("wind_down", "leave", "strong_leave", "late_leave", "hard_stop")},
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
        self._assistant_last_attempt = float("-inf")
        self._assistant_last_periodic = time.monotonic()
        self._assistant_last_chat_at = float("-inf")
        self._assistant_important_event_at = float("-inf")
        self._assistant_dialogue_mode = None
        self._assistant_notification_event = None
        self._assistant_local_rotation = 0
        self._chat_phase = "idle"
        self._last_chat_reply = ""
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
            # Start after the service's matching cooldown clock so the first
            # due attempt is not rejected and delayed for another interval.
            self._assistant_last_periodic = time.monotonic()
            self._assistant_windows = AssistantWindows(
                self.root, self._assistant_service,
                context=self._assistant_tools.context, dispatch=self._dispatch_assistant_tool,
                on_chat_state=self._show_chat_phase,
                proactive_status=self._proactive_status,
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
        # Retain the phase label holder; each reading bubble has its own small,
        # explicit chat button so reading/scrolling never opens another window.
        self._chat_button = button
        self._chat_speech = self._new_speech_bubble("")
        self._chat_speech.bind("<Button-1>", self._activate_chat_reply)
        self._chat_speech.bind("<Button-3>", self._dismiss_chat_reply)
        for bubble in (self.speech, self._chat_speech):
            bubble.set_chat_command(self._open_assistant_chat)
            bubble.set_activity_callback(self._note_assistant_activity)
            bubble.text_widget.bind("<Button-3>", self._dismiss_chat_reply)
            bubble.bind("<<SpeechLayoutChanged>>", self._queue_chat_hitbox_sync, add="+")
            for widget in (bubble, bubble.text_widget, bubble.scrollbar, bubble.chat_button):
                for event in ("<Configure>", "<Map>"):
                    widget.bind(event, self._queue_chat_hitbox_sync, add="+")
        if os.name == "nt":
            self._chat_hitbox = SpeechHitbox(self.root, self._activate_chat_reply, self._dismiss_chat_reply,
                                             on_scroll=self._scroll_visible_speech)
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
        if self._chat_hitbox is None:
            return
        try:
            speech = self._visible_speech()
            if (
                self.current_page == "timer" and speech is not None and speech.winfo_viewable()
            ):
                self._chat_hitbox.show_over(speech)
            else:
                self._chat_hitbox.hide()
        except (OSError, tk.TclError):
            core.log.exception("speech hitbox failed")
            self._chat_hitbox.close()
            self._chat_hitbox = None

    def _set_character(self, role):
        self._timer_character_role = role
        # A retained answer must not freeze the character in its neutral pose
        # while the timer moves into away, break, or end-of-day states.
        override = _CHAT_ROLE.get(self._chat_phase, role) if self._chat_phase != "reply" else role
        return super()._set_character(override)

    def _local_dialogue(self, kind, work_mode):
        personality = getattr(self.preferences, "personality", "balanced")
        if kind == "playful" and work_mode == "normal":
            self._assistant_local_rotation += 1
            custom = maybe_pick_custom(getattr(self.preferences, "custom_dialogue", ""))
            if custom:
                return custom
            rare = maybe_pick_rare(personality)
            if rare:
                return rare
            daily = maybe_pick_daily_temperament(date.today().isoformat())
            if daily:
                return daily
            # Time-aware messages used to live only in the old click-to-cycle
            # path. Rotate them into ordinary dialogue without reducing the
            # whole day to the same three time-of-day lines.
            if self._assistant_local_rotation % 3 == 1:
                kind = time_of_day_kind(datetime.now().hour)
        return pick(kind, personality=personality)

    def _say(self, kind, text=None, work_mode="normal"):
        routine = (self._assistant_dialogue_mode is not None
                   and self._assistant_dialogue_mode == self.last_work_mode)
        if not routine and (text is not None or kind not in {"playful", "cheer"} or work_mode != "normal"):
            self._assistant_important_event_at = time.monotonic()
        if text is None:
            text = self._local_dialogue(kind, work_mode)
        result = super()._say(kind, text, work_mode)
        speech = self.speech.cget("text")
        if speech and (not self._assistant_recent_dialogue or self._assistant_recent_dialogue[-1] != speech):
            self._assistant_recent_dialogue.append(speech)
        event = self._assistant_notification_event or _LOCAL_DIALOGUE_EVENTS.get(kind)
        if event is not None and not routine:
            # An actual timer notification can replace the retained widget
            # answer. Clearing the view does not count as reading/typing, and
            # the answer remains available in the conversation history.
            if self._chat_phase == "reply":
                self._show_chat_phase("cleared")
            self._record_assistant_notification(speech, event=event)
        return result

    def _record_assistant_notification(self, text, *, event, origin="local_event"):
        service = self._assistant_service
        if service is None:
            return
        try:
            turn_id = service.record_notification(text, event=event, origin=origin)
        except Exception:
            core.log.warning("Could not record assistant notification: %s", event)
            return
        if turn_id is not None and self._assistant_windows is not None:
            try:
                self._assistant_windows.refresh_chat_history()
            except Exception:
                core.log.warning("Could not refresh assistant notification history")

    def _cancel_chat_expiry(self):
        if self._chat_expiry is not None:
            self.root.after_cancel(self._chat_expiry)
            self._chat_expiry = None

    def _show_chat_phase(self, phase, text=""):
        if phase == "activity":
            self._note_assistant_activity()
            return
        incoming_phase = phase
        if phase == "cleared":
            self._last_chat_reply = ""
            phase = "idle"
        elif phase == "waiting":
            self._last_chat_reply = ""
        elif phase == "reply":
            self._last_chat_reply = text
        elif phase == "idle" and self._last_chat_reply:
            phase, text = "reply", self._last_chat_reply
        if incoming_phase != "cleared" and (phase != "idle" or self._chat_phase != "idle"):
            self._assistant_last_chat_at = time.monotonic()
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
            super()._set_character(self._timer_character_role if phase == "reply" else _CHAT_ROLE[phase])
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
        self._chat_speech.configure(text=text)
        # Keep the answer until a new send, explicit dismissal, or a later
        # opt-in AI conversation. Ordinary timer chatter never erases it.

    def _activate_chat_reply(self, _event=None):
        self._visible_speech().focus_reading()
        return "break"

    def _scroll_visible_speech(self, delta):
        if delta:
            units = max(1, abs(int(delta / 120))) * 3
            self._visible_speech().scroll(-units if delta > 0 else units)

    def _dismiss_chat_reply(self, _event=None):
        if self._chat_phase in {"reply", "error"}:
            self._show_chat_phase("cleared")
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
        return self._assistant_windows.confirm_change(description, cancelled)

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
        previous_event = self._assistant_notification_event
        self._assistant_notification_event = "break_started"
        try:
            super().accept_break()
        finally:
            self._assistant_notification_event = previous_event
        self._request_proactive("break_started", self.toast if self.toast is not previous_toast else None)

    def show_break_toast(self, text, allow_snooze=True):
        previous_toast = self.toast
        result = super().show_break_toast(text, allow_snooze=allow_snooze)
        # The desktop layer can suppress a toast after the timer gate checked
        # fullscreen state. Only a newly delivered alert enters the history.
        if self.toast is not None and self.toast is not previous_toast and self.toast.winfo_exists():
            self._say("break", text, work_mode=self._current_workday_state().mode)
        return result

    def _tick_safe(self):
        was_away = self.state.session.is_away
        previous_mode = self.last_work_mode
        previous_alert = self.break_gate.last_shown_at
        previous_toast = self.toast
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
        else:
            # AI cadence is independent of the local message rotation. An AI
            # reply refreshes last_dialogue_at, which otherwise postpones the
            # next one-minute attempt until the ordinary line changes again.
            self._request_proactive("periodic")

    def _update_dialogue(self):
        # Keep the already visible local fallback during a short AI request,
        # so an unrelated periodic line does not invalidate the arriving AI
        # text. Real timer transitions and alerts retain their normal path.
        now = time.monotonic()
        mode = self._current_workday_state().mode
        if self._assistant_pending is not None and self._assistant_pending.cancel.is_set():
            self._assistant_pending = None
        if mode == self.last_work_mode:
            if self._chat_blocks_proactive():
                return
            pending = self._assistant_pending
            if pending is not None and now - pending.started_at < _PROACTIVE_MAX_AGE:
                return
            service = self._assistant_service
            chatter = service is not None and service.load_settings().chatter_enabled
            if chatter and mode == "normal":
                # Chatter was explicitly selected as AI-only. Keep the last
                # visible text during failures or limits; diagnostics explain
                # the pause instead of disguising a canned line as AI output.
                # Mode transitions and real timer alerts still run normally.
                return
        # The core rotates worry/nag every minute after a snooze. That is
        # ordinary dialogue, not a fresh alert that should renew the quiet
        # period forever. A real workday transition still follows _say's
        # important-event path, even during reading or AI-only chatter.
        # Compare the original mode with the core's updated last_work_mode
        # so a transition between the two mode lookups is still an alert.
        previous_dialogue_mode = self._assistant_dialogue_mode
        self._assistant_dialogue_mode = self.last_work_mode
        try:
            super()._update_dialogue()
        finally:
            self._assistant_dialogue_mode = previous_dialogue_mode

    def _cycle_message(self, event=None):
        self._open_assistant_chat()

    def _cancel_proactive(self):
        if self._assistant_pending is not None:
            self._assistant_pending.cancel.set()
            self._assistant_pending = None

    def _chat_blocks_proactive(self):
        windows = self._assistant_windows
        if windows is not None and windows.is_chat_active():
            return True
        return (self._chat_phase not in {"idle", "reply"}
                or time.monotonic() - self._assistant_last_chat_at < _RECENT_CHAT_QUIET_SECONDS)

    def _note_assistant_activity(self):
        """Protect reading and typing without clearing the visible answer."""
        self._assistant_last_chat_at = time.monotonic()
        self._cancel_proactive()

    def _proactive_status(self):
        """A read-only UI snapshot; checking this never starts an API request."""
        service = self._assistant_service
        if service is None:
            return {"reason": "AI 서비스를 준비하지 못했어요.", "next_in_seconds": None}
        settings = service.load_settings()
        snapshot = service.proactive_diagnostics()
        now = time.monotonic()
        remaining = max(
            snapshot["retry_after_seconds"],
            self._assistant_last_attempt + _PROACTIVE_MIN_SPACING - now,
            self._assistant_last_periodic + settings.proactive_interval_minutes * 60 - now,
            self._assistant_last_chat_at + _RECENT_CHAT_QUIET_SECONDS - now,
            self._assistant_important_event_at + _IMPORTANT_EVENT_SECONDS - now,
            0,
        )
        result = {**snapshot, "next_in_seconds": math.ceil(remaining)}
        if not settings.proactive_enabled and not settings.chatter_enabled:
            reason = "먼저 말 걸기와 AI 재잘대기가 모두 꺼져 있어요."
        elif not settings.enabled:
            reason = "AI 대화 사용이 꺼져 있어요."
        elif not service.has_key():
            reason = "API 키가 등록되지 않았어요."
        elif settings.proactive_quiet_until == date.today().isoformat():
            reason = "오늘은 AI 먼저 말 걸기를 쉬고 있어요."
        elif snapshot["state"] == "requesting":
            reason = "AI 응답을 기다리고 있어요. 추가 요청은 보내지 않아요."
        elif self._assistant_windows is not None and self._assistant_windows.is_chat_active():
            reason = self._assistant_windows.chat_activity_reason()
        elif now - self._assistant_last_chat_at < _RECENT_CHAT_QUIET_SECONDS:
            reason = "대화·읽기 뒤 5분 동안 쉬고 있어요."
        elif now - self._assistant_important_event_at < _IMPORTANT_EVENT_SECONDS:
            reason = "중요한 타이머 알림을 읽을 수 있도록 정기 대화를 1분 동안 쉬어요."
        elif self._break_notifications_suppressed():
            reason = "전체 화면 등 현재 알림을 보류하는 상태예요."
        elif not self.preferences.show_message:
            reason = "말풍선 표시가 꺼져 있어 정기 대화를 쉬고 있어요."
        elif self.current_page != "timer" or not self.root.winfo_viewable():
            reason = "타이머 위젯이 보일 때 정기 대화를 이어가요."
        elif "periodic" not in settings.proactive_events and not settings.chatter_enabled:
            reason = "정기 말 걸기는 꺼져 있고, 선택한 타이머 상황에서만 말해요."
        else:
            context = self._assistant_tools.context()
            if context.get("is_away"):
                reason = "자리비움 중에는 정기 대화를 쉬고 있어요."
            elif context.get("workday_mode") != "normal":
                reason = "업무 마무리 시간에는 정기 대화를 쉬고 있어요."
            elif remaining:
                reason = f"다음 정기 시도까지 약 {math.ceil(remaining)}초 남았어요."
            else:
                reason = "다음 타이머 갱신 때 정기 대화를 시도할 수 있어요. 사용량 한도는 계속 적용돼요."
        result["reason"] = reason
        return result

    def _request_proactive(self, event, toast=None):
        service = self._assistant_service
        if event != "periodic":
            self._assistant_important_event_at = time.monotonic()
            self._assistant_events.append({"date": date.today().isoformat(), "time": datetime.now().astimezone().isoformat(timespec="seconds"), "event": event})
        if self._chat_blocks_proactive():
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
            if now - self._assistant_important_event_at < _IMPORTANT_EVENT_SECONDS:
                return
            interval = service.load_settings().proactive_interval_minutes * 60
            if now - self._assistant_last_periodic < interval:
                return
            context = self._assistant_tools.context()
            if context.get("is_away") or context.get("workday_mode") != "normal":
                return
        # The worker records its attempt slightly after this UI thread. Check
        # its authoritative time gate before advancing either UI clock; a
        # sub-second delay must not turn a one-minute interval into two.
        admission = service.proactive_diagnostics(event)
        if admission["state"] == "requesting" or admission["retry_after_seconds"] > 0:
            return
        if event == "periodic":
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
            or service is None or service.revision != request.revision or not service.can_proactively_speak(request.event)
            or self._break_notifications_suppressed()
            or self._chat_blocks_proactive()
            or request.event == "periodic" and time.monotonic() - self._assistant_important_event_at < _IMPORTANT_EVENT_SECONDS
        ):
            return
        current = self._assistant_tools.context()
        if any(current[key] != request.context[key] for key in ("date", "is_away", "workday_mode", "break_reminders_enabled_today")):
            return
        if request.toast is not None:
            toast = request.toast
            if text and self.toast is toast and toast.winfo_exists() and hasattr(toast, "body_label"):
                toast.body_label.configure(text=text[:89].rstrip() + "…" if len(text) > 90 else text)
                self._record_assistant_notification(text, event=request.event, origin="proactive")
            return
        if (
            self.last_dialogue_at != request.last_dialogue_at or not self.preferences.show_message
            or self.current_page != "timer" or not self.root.winfo_viewable()
        ):
            return
        if text:
            if self._chat_phase == "reply":
                # The prior answer remains in chat history. Only a fresh,
                # permitted AI message may replace its retained widget view.
                self._show_chat_phase("cleared")
            self.speech.configure(text=text)
            self._assistant_recent_dialogue.append(text)
            self.last_dialogue_at = time.monotonic()
            self._apply_widget_appearance()
            self._record_assistant_notification(text, event=request.event, origin="proactive")
