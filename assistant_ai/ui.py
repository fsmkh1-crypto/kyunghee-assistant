from __future__ import annotations

from datetime import datetime
from queue import Empty, SimpleQueue
import re
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox, ttk
import tkinter.font as tkfont
from urllib.parse import urlsplit
import webbrowser

from app import AMBER, BG, BORDER, MUTED, PANEL, PANEL_2, PURPLE, PURPLE_2, TEXT
from app_brand import APP_NAME

from .api import AIError
from .config import AISettings, DEFAULT_WEATHER_LOCATION, MODEL_PRICES, MODELS, SettingsError
from .weather import WeatherError


HISTORY_PAGE_SIZE = 40
_SOURCE_LINK = re.compile(
    r"\[(?P<label>[^\]\r\n]{1,160})\]\(\s*"
    r"(?:<(?P<angled>[^\s<>]+)>|(?P<simple>[^\s()<>]+(?:\([^\s()]*\)[^\s()<>]*)*))\s*\)"
    r"|(?P<bare>https?://[^\s<>\"`]+)",
    re.IGNORECASE,
)


def _font(parent, size=10):
    return parent.winfo_toplevel().font_family, size


def _label(parent, text="", *, size=10, color=TEXT, **options):
    return tk.Label(
        parent, text=text, font=_font(parent, size), bg=parent.cget("bg"),
        fg=color, anchor="w", justify="left", **options,
    )


def _button(parent, text, command, *, primary=False):
    return tk.Button(
        parent, text=text, command=command, font=_font(parent, 9), fg=TEXT,
        bg=PURPLE if primary else PANEL_2, activeforeground=TEXT,
        activebackground=PURPLE_2 if primary else BORDER, disabledforeground=MUTED,
        relief="flat", bd=0, padx=10, pady=6, cursor="hand2",
    )


def _entry(parent, variable, **options):
    return tk.Entry(
        parent, textvariable=variable, font=_font(parent), fg=TEXT, bg=PANEL_2,
        insertbackground=TEXT, relief="flat", highlightthickness=1,
        highlightbackground=BORDER, highlightcolor=PURPLE, **options,
    )


def _text(parent, **options):
    return tk.Text(
        parent, wrap="word", width=1, font=_font(parent), fg=TEXT, bg=PANEL_2,
        insertbackground=TEXT, relief="flat", highlightthickness=1,
        highlightbackground=BORDER, highlightcolor=PURPLE, padx=9, pady=7, **options,
    )


def _add_scrollbar(frame, widget):
    bar = tk.Scrollbar(frame, command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)


def _local_time(value):
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone().strftime("%m-%d %H:%M")
    except (AttributeError, ValueError):
        return ""


def _source_url(raw, *, bare=True):
    url = raw
    if bare:
        url = url.rstrip(".,;:!?}'")
        while url.endswith(")") and url.count(")") > url.count("("):
            url = url[:-1]
        while url.endswith("]") and url.count("]") > url.count("["):
            url = url[:-1]
    if "\\" in url or any(ord(char) < 32 for char in url):
        return ""
    try:
        parts = urlsplit(url)
        host = parts.hostname
        if parts.scheme in {"http", "https"} and host and "%" not in host and parts.username is None:
            if parts.port is None or parts.port > 0:
                return url
    except ValueError:
        pass
    return ""


def _open_source(url):
    Thread(target=webbrowser.open_new_tab, args=(url,), daemon=True).start()


class _SourceLinks:
    def __init__(self, widget):
        self.widget = widget
        self.targets = {}
        widget.tag_configure("source", foreground="#B9D6FF", underline=True)
        widget.tag_bind("source", "<Enter>", lambda _event: widget.configure(cursor="hand2"))
        widget.tag_bind("source", "<Leave>", lambda _event: widget.configure(cursor="xterm"))
        widget.tag_bind("source", "<ButtonRelease-1>", self._follow)

    def _follow(self, event):
        for tag in self.widget.tag_names(f"@{event.x},{event.y}"):
            if tag in self.targets:
                _open_source(self.targets[tag])
                return "break"

    def clear(self):
        for tag in self.targets:
            self.widget.tag_delete(tag)
        self.targets.clear()
        self.widget.configure(cursor="xterm")

    def insert(self, text):
        widget = self.widget
        start = 0
        for match in _SOURCE_LINK.finditer(text):
            bare = match.group("bare")
            url = _source_url(bare or match.group("angled") or match.group("simple"), bare=bare is not None)
            if not url:
                continue
            widget.insert("end", text[start:match.start()])
            label = match.group("label")
            if bare:
                label = url
                start = match.start() + len(url)
            else:
                if label.isdecimal():
                    label = f"[{label}]"
                start = match.end()
            tag = f"source_{len(self.targets)}"
            self.targets[tag] = url
            widget.insert("end", label, ("source", tag))
        widget.insert("end", text[start:])


class AssistantWindows:
    """The timer owns one Tk loop. Workers pass AI results to it through a queue."""

    def __init__(self, root, service, *, context, dispatch, on_chat_state=None, chat_work_area=None):
        self.root = root
        self.service = service
        self.context = context
        self.dispatch = dispatch
        self.on_chat_state = on_chat_state
        self.chat_work_area = chat_work_area
        families = {name.casefold() for name in tkfont.families(root)}
        self.font_family = next(
            (name for name in ("Pretendard", "Malgun Gothic", "Noto Sans CJK KR") if name.casefold() in families),
            tkfont.nametofont("TkDefaultFont", root=root).actual("family"),
        )
        self.chat_window = None
        self.memory_window = None
        self.settings_window = None
        self.reply_window = None
        self.weather_window = None
        self._weather_results = SimpleQueue()
        self._weather_poll_id = None
        self._poll_id = None
        self._cancel = None
        self._results = SimpleQueue()
        self._closed = False
        self._sent_text = ""
        self._previous_turns = []
        self._history_limit = HISTORY_PAGE_SIZE
        self._chat_state = ("idle", "")

    def _set_chat_state(self, phase, text=""):
        state = (phase, text)
        if state == self._chat_state:
            return
        self._chat_state = state
        if self.on_chat_state is not None:
            self.on_chat_state(phase, text)

    def _draft_changed(self):
        if self._cancel is not None or self.chat_window.state() == "withdrawn":
            return
        if self.chat_window.input.get("1.0", "end-1c").strip():
            self._set_chat_state("composing")
        elif self._chat_state[0] == "composing":
            self._set_chat_state("idle")

    def open_chat(self):
        if self._closed:
            return
        if self.chat_window is None:
            self.chat_window = _ChatWindow(self)
            self._place_chat_window()
        self.chat_window.show()
        self.chat_window.input.focus_set()
        if self._cancel is None:
            self.chat_window.update_availability()
            self._render_history()
            self._draft_changed()

    def _place_chat_window(self):
        root = self.root
        root.update_idletasks()
        x, y = root.winfo_rootx(), root.winfo_rooty()
        widget_width, widget_height = root.winfo_width(), root.winfo_height()
        if self.chat_work_area is None:
            left, top = root.winfo_vrootx(), root.winfo_vrooty()
            right, bottom = left + root.winfo_vrootwidth(), top + root.winfo_vrootheight()
        else:
            left, top, right, bottom = self.chat_work_area(x, y, widget_width, widget_height)

        gap = 16
        left, right = left + gap, right - gap
        top, bottom = top + gap, bottom - 3 * gap
        min_width, min_height = self.chat_window.MIN_SIZE
        width, height = self.chat_window.DEFAULT_SIZE
        width = max(min_width, min(width, right - left))
        height = max(min_height, min(height, bottom - top))
        left_room = x - gap - left
        right_x = x + widget_width + gap
        right_room = right - right_x
        below_y = y + widget_height + gap
        below_room = bottom - below_y
        above_room = y - gap - top

        if right_room >= min_width and (right_room >= width or right_room >= left_room):
            width = min(width, right_room)
            x = right_x
        elif left_room >= min_width:
            width = min(width, left_room)
            x -= width + gap
        elif below_room >= min_height and (below_room >= height or below_room >= above_room):
            height = min(height, below_room)
            y = below_y
        elif above_room >= min_height:
            height = min(height, above_room)
            y -= height + gap
        else:
            x = right_x if right_room >= left_room else x - width - gap

        x = max(left, min(x, right - width))
        y = max(top, min(y, bottom - height))
        self.chat_window.geometry(f"{width}x{height}+{x}+{y}")

    def open_memories(self):
        if self._closed:
            return
        if self.memory_window is None:
            self.memory_window = _MemoryWindow(self)
        self.memory_window.refresh()
        self.memory_window.show()
        self.memory_window.search_entry.focus_set()

    def open_settings(self):
        if self._closed:
            return
        if self.settings_window is None:
            self.settings_window = _SettingsWindow(self)
        if self.settings_window.state() == "withdrawn":
            self.settings_window.reload()
        self.settings_window.refresh_usage()
        self.settings_window.show()

    def open_reply(self, text):
        if self._closed:
            return
        if self.reply_window is None:
            self.reply_window = _ReadoutWindow(self, "승아의 답변")
            self.reply_window.add_action("대화 계속하기", self._resume_chat)
        self.reply_window.set_text(text)
        self.reply_window.show()
        self.reply_window.text.focus_set()

    def _resume_chat(self):
        self.reply_window.withdraw()
        self.open_chat()

    def open_weather(self):
        if self._closed:
            return
        if self.weather_window is None:
            self.weather_window = _ReadoutWindow(self, "날씨 조회")
            self.weather_window.add_action("기본 지역 설정", self.open_weather_settings)
            self.weather_window.add_action("다시 조회", self.open_weather)
        self.weather_window.show()
        if self._weather_poll_id is not None:
            return
        self.weather_window.set_text("기상정보를 조회하고 있어요…")
        Thread(target=self._request_weather, daemon=True).start()
        self._weather_poll_id = self.root.after(70, self._poll_weather)

    def open_weather_settings(self):
        if not self._closed:
            self.open_settings()
            self.settings_window.weather_entry.focus_set()

    def _request_weather(self):
        try:
            report = self.service.weather_report()
        except (AIError, SettingsError, WeatherError) as error:
            report = str(error)
        except Exception:
            report = "기상정보를 가져오지 못했어요. 잠시 뒤 다시 시도해 주세요."
        if not isinstance(report, str) or not report.strip():
            report = "조회 결과를 표시할 수 없어요. 잠시 뒤 다시 시도해 주세요."
        self._weather_results.put(report)

    def _poll_weather(self):
        self._weather_poll_id = None
        try:
            report = self._weather_results.get_nowait()
        except Empty:
            self._weather_poll_id = self.root.after(70, self._poll_weather)
            return
        self.weather_window.set_text(report)

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._cancel is not None:
            self._cancel.set()
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        if self._weather_poll_id is not None:
            self.root.after_cancel(self._weather_poll_id)
            self._weather_poll_id = None
        self._set_chat_state("idle")
        for window in (self.chat_window, self.memory_window, self.settings_window, self.reply_window, self.weather_window):
            if window is not None:
                window.destroy()

    def hide(self):
        for window in (self.chat_window, self.memory_window, self.settings_window, self.reply_window, self.weather_window):
            if window is not None:
                window._hide()

    def confirmation_parent(self):
        if self.chat_window is not None and self.chat_window.winfo_viewable():
            return self.chat_window
        return self.root

    def settings_changed(self):
        if self.chat_window is not None and self._cancel is None:
            self.chat_window.update_availability()
            self._render_history()
        if self.memory_window is not None:
            self.memory_window.refresh()

    def _render_history(self, *, pending=""):
        try:
            turns = self.service.recent_turns(limit=self._history_limit + 1)
        except Exception:
            self.chat_window.status.set("대화 기록을 불러오지 못했어요.")
            return None
        self.chat_window.has_older = len(turns) > self._history_limit
        self.chat_window.update_older_button()
        turns = turns[-self._history_limit:]
        self.chat_window.render(turns, pending=pending)
        return turns

    def show_older(self):
        self._history_limit += HISTORY_PAGE_SIZE
        if self._render_history() is not None:
            self.chat_window.history.yview_moveto(0)

    def send(self):
        if self._cancel is not None or not self.chat_window.update_availability():
            return
        text = self.chat_window.input.get("1.0", "end-1c").strip()
        if not text:
            self.chat_window.status.set("보낼 메시지를 입력해 주세요.")
            return
        try:
            context = self.context()
        except Exception:
            self.chat_window.status.set("타이머 상태를 확인하지 못했어요. 다시 시도해 주세요.")
            self._set_chat_state("error")
            return
        self._previous_turns = self._render_history(pending=text)
        self._sent_text = text
        self._cancel = Event()
        self.chat_window.input.delete("1.0", "end")
        self.chat_window.input.edit_modified(False)
        self.chat_window.set_busy(True)
        self.chat_window.status.set("승아가 답을 준비하고 있어요…")
        worker = Thread(target=self._request, args=(text, context, self._cancel), daemon=True)
        worker.start()
        self._poll_id = self.root.after(60, self._poll)
        self._set_chat_state("waiting")

    def _request(self, text, context, cancel):
        try:
            reply = self.service.chat(text, context=context, dispatch=self.dispatch, cancel=cancel)
        except (AIError, SettingsError) as error:
            self._results.put((None, str(error)))
        except Exception:
            self._results.put((None, "대화 중 문제가 생겼어요. 다시 시도해 주세요."))
        else:
            self._results.put((reply, ""))

    def _poll(self):
        self._poll_id = None
        try:
            reply, error = self._results.get_nowait()
        except Empty:
            self._poll_id = self.root.after(60, self._poll)
            if self._cancel.is_set():
                self._set_chat_state("idle")
            return
        cancelled = self._cancel.is_set()
        self._cancel = None
        self.chat_window.set_busy(False)
        self.chat_window.update_availability()
        turns = self._render_history()
        if reply and not cancelled and turns is None:
            self.chat_window.render([], pending=self._sent_text, reply=reply)
        if error or cancelled:
            if turns is not None and turns == self._previous_turns:
                if not self.chat_window.input.get("1.0", "end-1c").strip():
                    self.chat_window.input.insert("1.0", self._sent_text)
                    self.chat_window.input.edit_modified(False)
            self.chat_window.status.set("대화 요청을 취소했어요." if cancelled else error)
        self._sent_text = ""
        self._previous_turns = []
        if cancelled or self.chat_window.state() == "withdrawn":
            self._set_chat_state("idle")
        elif reply:
            self._set_chat_state("reply", reply)
        else:
            self._set_chat_state("error")
        if self.settings_window is not None:
            self.settings_window.refresh_usage()
        if reply and not cancelled and self.memory_window is not None and self.memory_window.winfo_viewable():
            self.memory_window.refresh()

    def cancel(self):
        if self._cancel is not None:
            self._cancel.set()
            self.chat_window.cancel_button.configure(state="disabled")
            self.chat_window.status.set("취소 요청 중…")
        self._set_chat_state("idle")

    def clear_history(self):
        if self._cancel is not None:
            return
        if not messagebox.askyesno(
            "대화 기록 지우기", "저장된 대화와 이번 실행 중의 대화를 모두 지울까요?",
            parent=self.chat_window,
        ):
            return
        try:
            self.service.clear_history()
        except Exception:
            self.chat_window.status.set("대화 기록을 지우지 못했어요.")
            return
        self._history_limit = HISTORY_PAGE_SIZE
        if self._render_history() is not None:
            self.chat_window.status.set("대화 기록을 지웠어요.")
        self._set_chat_state("idle")


class _Window(tk.Toplevel):
    def __init__(self, owner, title, width, height):
        super().__init__(owner.root, bg=BG)
        self.owner = owner
        self.service = owner.service
        self.font_family = owner.font_family
        self.withdraw()
        self.title(f"{title} | {APP_NAME}")
        self.geometry(f"{width}x{height}")
        self.protocol("WM_DELETE_WINDOW", self._hide)
        self.bind("<Escape>", self._hide)
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=12, pady=12)

    def _hide(self, _event=None):
        self.withdraw()
        return "break"

    def show(self):
        self.deiconify()
        self.lift()


class _ReadoutWindow(_Window):
    def __init__(self, owner, title):
        super().__init__(owner, title, 700, 520)
        self.minsize(430, 320)
        _label(self.body, title, size=15).pack(anchor="w", padx=16, pady=(12, 8))
        self.actions = tk.Frame(self.body, bg=PANEL)
        self.actions.pack(side="bottom", fill="x", padx=16, pady=(10, 12))
        _button(self.actions, "닫기", self._hide).pack(side="right")
        frame = tk.Frame(self.body, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=16)
        self.text = _text(frame, state="disabled")
        font = _font(self, 15)
        line_gap = max(1, round(tkfont.Font(root=self, font=font).metrics("linespace") * 0.4))
        self.text.configure(font=font, fg="#FFFFFF", padx=14, pady=12, spacing2=line_gap, spacing3=line_gap)
        _add_scrollbar(frame, self.text)
        self._sources = _SourceLinks(self.text)

    def add_action(self, caption, command):
        _button(self.actions, caption, command).pack(side="left", padx=(0, 6))

    def set_text(self, text):
        widget = self.text
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        self._sources.clear()
        self._sources.insert(text)
        widget.configure(state="disabled")
        widget.yview_moveto(0)


class _ChatWindow(_Window):
    DEFAULT_SIZE = (640, 590)
    MIN_SIZE = (500, 420)

    def __init__(self, owner):
        super().__init__(owner, "승아와 대화", *self.DEFAULT_SIZE)
        self.minsize(*self.MIN_SIZE)
        header = tk.Frame(self.body, bg=PANEL)
        header.pack(fill="x", padx=12, pady=(10, 4))
        _label(header, "승아와 대화", size=15).pack(side="left")
        _button(header, "API 설정", owner.open_settings).pack(side="right")
        _button(header, "기억 관리", owner.open_memories).pack(side="right", padx=(0, 6))
        _button(header, "날씨", owner.open_weather).pack(side="right", padx=(0, 6))
        self.privacy = tk.StringVar(master=self)
        privacy = _label(self.body, color=MUTED, textvariable=self.privacy, wraplength=580)
        privacy.pack(fill="x", padx=12, pady=(0, 7))
        privacy.bind("<Configure>", lambda event: privacy.configure(wraplength=event.width))

        history_frame = tk.Frame(self.body, bg=PANEL)
        self.history = _text(history_frame, height=4, state="disabled")
        self.history.tag_configure("user", foreground="#C4B5FD", spacing1=6)
        self.history.tag_configure("assistant", foreground="#86EFAC", spacing1=6)
        self.history.tag_configure("note", foreground=MUTED)
        self._sources = _SourceLinks(self.history)
        _add_scrollbar(history_frame, self.history)

        composer = tk.Frame(self.body, bg=PANEL)
        composer.pack(side="bottom", fill="x")
        _label(composer, "메시지 · Ctrl+Enter로 보내기", color=MUTED, size=9).pack(
            anchor="w", padx=12, pady=(8, 3)
        )
        input_frame = tk.Frame(composer, bg=PANEL)
        input_frame.pack(fill="x", padx=12)
        self.input = _text(input_frame, height=4, undo=True)
        _add_scrollbar(input_frame, self.input)
        self.input.bind("<Control-Return>", self._send_from_keyboard)
        self.input.bind("<<Modified>>", self._input_modified)
        self.status = tk.StringVar(master=self)
        status = _label(composer, color=AMBER, textvariable=self.status, wraplength=580)
        status.pack(fill="x", padx=12, pady=(5, 0))
        status.bind("<Configure>", lambda event: status.configure(wraplength=event.width))

        controls = tk.Frame(composer, bg=PANEL)
        controls.pack(fill="x", padx=12, pady=(4, 10))
        self.clear_button = _button(controls, "대화 기록 지우기", owner.clear_history)
        self.clear_button.pack(side="left")
        self.older_button = _button(controls, "이전 대화 더 보기", owner.show_older)
        self.older_button.pack(side="left", padx=(6, 0))
        self.send_button = _button(controls, "보내기", owner.send, primary=True)
        self.send_button.pack(side="right")
        self.cancel_button = _button(controls, "응답 취소", owner.cancel)
        self.cancel_button.pack(side="right", padx=(0, 6))
        self.has_older = False
        self.set_busy(False)
        history_frame.pack(fill="both", expand=True, padx=12)

    def _hide(self, _event=None):
        self.owner.cancel()
        return super()._hide()

    def _send_from_keyboard(self, _event):
        self.owner.send()
        return "break"

    def _input_modified(self, _event):
        if self.input.edit_modified():
            self.input.edit_modified(False)
            self.owner._draft_changed()

    def update_availability(self):
        try:
            settings = self.service.load_settings()
            ready = self.service.ready()
        except Exception:
            self.privacy.set("AI 설정을 불러오지 못했어요.")
            self.status.set("")
            self.send_button.configure(state="disabled")
            return False
        storage = "대화가 이 PC에 저장돼요." if settings.memory_enabled else "새 대화는 이번 실행 중에만 남아요."
        self.privacy.set(
            f"보낸 메시지, 관련 대화·기억, 타이머 상태가 OpenAI API에 전달될 수 있어요. {storage}"
        )
        if ready:
            self.status.set("")
        elif not settings.enabled:
            self.status.set("API 설정에서 AI 대화를 켜 주세요.")
        else:
            self.status.set("API 설정에서 OpenAI API 키를 등록해 주세요.")
        self.send_button.configure(state="normal" if ready else "disabled")
        return ready

    def set_busy(self, busy):
        self.clear_button.configure(state="disabled" if busy else "normal")
        self.cancel_button.configure(state="normal" if busy else "disabled")
        self.send_button.configure(state="disabled" if busy else "normal")
        self.update_older_button()

    def update_older_button(self):
        can_page = self.has_older and self.owner._cancel is None
        self.older_button.configure(state="normal" if can_page else "disabled")

    def render(self, turns, *, pending="", reply=""):
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        self._sources.clear()
        if not turns and not pending:
            self.history.insert("end", "승아에게 인사를 건네거나 필요한 일을 물어보세요.\n", "note")
        for turn in turns:
            timestamp = _local_time(turn.created_at)
            sender = f"나 · {timestamp}" if timestamp else "나"
            self._write(sender, turn.user, "user")
            if turn.assistant is None:
                self.history.insert("end", "응답 없음\n\n", "note")
            else:
                self._write("승아", turn.assistant, "assistant")
        if pending:
            self._write("나", pending, "user")
            if reply:
                self._write("승아", reply, "assistant")
            else:
                self.history.insert("end", "응답을 기다리는 중…\n", "note")
        self.history.configure(state="disabled")
        self.history.see("end")

    def _write(self, sender, text, tag):
        self.history.insert("end", f"{sender}\n", tag)
        if tag == "assistant":
            self._sources.insert(text)
        else:
            self.history.insert("end", text)
        self.history.insert("end", "\n\n")


class _MemoryWindow(_Window):
    def __init__(self, owner):
        super().__init__(owner, "기억 관리", 610, 550)
        self.minsize(490, 440)
        _label(self.body, "승아의 장기 기억", size=15).pack(anchor="w", padx=12, pady=(10, 4))
        self.privacy = tk.StringVar(master=self)
        privacy = _label(self.body, color=MUTED, textvariable=self.privacy, wraplength=550)
        privacy.pack(fill="x", padx=12, pady=(0, 7))
        privacy.bind("<Configure>", lambda event: privacy.configure(wraplength=event.width))

        search_row = tk.Frame(self.body, bg=PANEL)
        search_row.pack(fill="x", padx=12, pady=(0, 6))
        _label(search_row, "기억 검색").pack(side="left", padx=(0, 8))
        self.search = tk.StringVar(master=self)
        self.search_entry = _entry(search_row, self.search)
        self.search_entry.pack(side="left", fill="x", expand=True, ipady=3)
        _button(search_row, "지우기", lambda: self.search.set("")).pack(side="right", padx=(6, 0))

        list_frame = tk.Frame(self.body, bg=PANEL)
        self.listbox = tk.Listbox(
            list_frame, height=5, activestyle="none", exportselection=False, font=_font(self),
            fg=TEXT, bg=PANEL_2, selectforeground=TEXT, selectbackground=PURPLE_2,
            relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=PURPLE,
        )
        _add_scrollbar(list_frame, self.listbox)
        self.listbox.bind("<<ListboxSelect>>", self._show_selected)

        editor = tk.Frame(self.body, bg=PANEL)
        editor.pack(side="bottom", fill="x")
        detail_frame = tk.Frame(editor, bg=PANEL)
        detail_frame.pack(fill="x", padx=12, pady=(6, 0))
        self.detail = _text(detail_frame, height=4, state="disabled")
        _add_scrollbar(detail_frame, self.detail)
        controls = tk.Frame(editor, bg=PANEL)
        controls.pack(fill="x", padx=12, pady=(6, 0))
        self.delete_button = _button(controls, "선택한 기억 삭제", self._delete)
        self.delete_button.pack(side="left")
        self.clear_button = _button(controls, "모든 기억 삭제", self._clear)
        self.clear_button.pack(side="left", padx=(6, 0))
        _button(controls, "API 설정", owner.open_settings).pack(side="right")

        _label(editor, "새 기억 추가").pack(anchor="w", padx=12, pady=(8, 3))
        add_frame = tk.Frame(editor, bg=PANEL)
        add_frame.pack(fill="x", padx=12)
        self.add_text = _text(add_frame, height=3)
        _add_scrollbar(add_frame, self.add_text)
        footer = tk.Frame(editor, bg=PANEL)
        footer.pack(fill="x", padx=12, pady=(5, 10))
        self.add_button = _button(footer, "기억 저장", self._add, primary=True)
        self.add_button.pack(side="right")
        self.status = tk.StringVar(master=self)
        _label(footer, color=AMBER, textvariable=self.status, wraplength=375).pack(side="left", fill="x")
        self.entries = []
        self.visible_entries = []
        self.search.trace_add("write", self._filter)
        list_frame.pack(fill="both", expand=True, padx=12)

    def refresh(self):
        try:
            enabled = self.service.load_settings().memory_enabled
            self.entries = self.service.memory.list_memories()
        except Exception:
            enabled = False
            self.entries = []
            self.status.set("기억을 불러오지 못했어요.")
        else:
            self.status.set("")
        if enabled:
            self.privacy.set("기억은 이 PC에 저장돼요. 대화에 필요한 기억은 OpenAI API에 전달될 수 있어요.")
        else:
            self.privacy.set("장기 기억이 꺼져 있어요. 기존 기억을 찾아보거나 삭제할 수 있어요.")
        self.add_button.configure(state="normal" if enabled else "disabled")
        self.clear_button.configure(state="normal" if self.entries else "disabled")
        self._filter()

    def _selected(self):
        indices = self.listbox.curselection()
        return self.visible_entries[indices[0]] if indices else None

    def _filter(self, *_args):
        previous = self._selected()
        words = self.search.get().casefold().split()
        self.visible_entries = [
            entry for entry in self.entries if all(word in entry.text.casefold() for word in words)
        ]
        self.listbox.delete(0, "end")
        for index, entry in enumerate(self.visible_entries):
            summary = " ".join(entry.text.split())
            if len(summary) > 86:
                summary = summary[:85] + "…"
            self.listbox.insert("end", summary)
            if previous is not None and entry.id == previous.id:
                self.listbox.selection_set(index)
        self._show_selected()

    def _show_selected(self, _event=None):
        entry = self._selected()
        self.delete_button.configure(state="normal" if entry else "disabled")
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if entry is not None:
            timestamp = _local_time(entry.created_at)
            heading = f"저장 · {timestamp}\n\n" if timestamp else ""
            self.detail.insert("1.0", heading + entry.text)
        elif not self.visible_entries:
            self.detail.insert("1.0", "검색 결과가 없어요." if self.search.get().strip() else "저장된 기억이 없어요.")
        self.detail.configure(state="disabled")

    def _add(self):
        text = self.add_text.get("1.0", "end-1c").strip()
        if not text:
            self.status.set("저장할 내용을 입력해 주세요.")
            return
        try:
            entry = self.service.memory.add_memory(text)
        except Exception:
            self.status.set("기억을 저장하지 못했어요.")
            return
        if entry is None:
            self.refresh()
            self.status.set("API 설정에서 장기 기억을 켜 주세요.")
            return
        self.add_text.delete("1.0", "end")
        self.search.set("")
        self.refresh()
        self.status.set("기억을 저장했어요.")

    def _delete(self):
        entry = self._selected()
        if entry is None or not messagebox.askyesno("기억 삭제", "선택한 기억을 지울까요?", parent=self):
            return
        try:
            deleted = self.service.delete_memory(entry.id)
        except Exception:
            self.status.set("기억을 지우지 못했어요.")
            return
        self.refresh()
        self.status.set("기억을 지웠어요." if deleted else "이미 지워진 기억이에요.")

    def _clear(self):
        if not messagebox.askyesno("기억 삭제", "저장된 장기 기억을 모두 지울까요?", parent=self):
            return
        try:
            self.service.clear_memories()
        except Exception:
            self.status.set("기억을 지우지 못했어요.")
            return
        self.refresh()
        self.status.set("장기 기억을 모두 지웠어요.")


class _SettingsWindow(_Window):
    def __init__(self, owner):
        super().__init__(owner, "AI·API 설정", 650, 640)
        self.minsize(600, 460)
        self.status = tk.StringVar(master=self)
        footer = tk.Frame(self.body, bg=PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=(6, 10))
        _label(footer, color=AMBER, textvariable=self.status, wraplength=430).pack(side="left", fill="x")
        self.save_button = _button(footer, "설정 저장", self._save, primary=True)
        self.save_button.pack(side="right")

        canvas = tk.Canvas(self.body, bg=PANEL, highlightthickness=0, bd=0)
        _add_scrollbar(self.body, canvas)
        content = tk.Frame(canvas, bg=PANEL)
        content_id = canvas.create_window(0, 0, window=content, anchor="nw")
        content.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: canvas.itemconfigure(content_id, width=event.width))
        self.bind("<MouseWheel>", lambda event: canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        self.bind("<Button-4>", lambda _event: canvas.yview_scroll(-1, "units"))
        self.bind("<Button-5>", lambda _event: canvas.yview_scroll(1, "units"))

        _label(content, "AI·API 설정", size=15).pack(anchor="w", padx=12, pady=(10, 4))
        _label(
            content, "OpenAI API 이용료는 ChatGPT 구독과 별도로 청구돼요.", color=MUTED,
        ).pack(anchor="w", padx=12, pady=(0, 8))

        self.enabled = tk.BooleanVar(master=self)
        self.proactive = tk.BooleanVar(master=self)
        self.memory = tk.BooleanVar(master=self)
        for variable, caption in (
            (self.enabled, "승아의 AI 대화 사용"),
            (self.proactive, "타이머 이벤트에서 AI 응원·안내 허용"),
            (self.memory, "대화 기록과 장기 기억을 이 PC에 저장하고 다음 대화에 활용"),
        ):
            tk.Checkbutton(
                content, text=caption, variable=variable, font=_font(self), fg=TEXT, bg=PANEL,
                activeforeground=TEXT, activebackground=PANEL, selectcolor=PANEL_2, bd=0,
                highlightthickness=0, cursor="hand2",
            ).pack(anchor="w", padx=12, pady=1)
        _label(
            content,
            "AI 응원·안내도 API 사용량에 포함돼요. 타이머 상태와 최근 대화가 전송될 수 있고, 이번 실행 중에만 남는 대화도 포함돼요.",
            size=9, color=MUTED, wraplength=530,
        ).pack(fill="x", padx=12, pady=(3, 0))

        weather = tk.Frame(content, bg=PANEL)
        weather.pack(fill="x", padx=12, pady=(12, 2))
        weather.columnconfigure(1, weight=1)
        self.weather_location = tk.StringVar(master=self, value=DEFAULT_WEATHER_LOCATION)
        self.weather_entry = _entry(weather, self.weather_location)
        self._field(weather, 0, "기본 날씨 지역", self.weather_entry)
        _label(weather, "예시 세종시, 대전시, 서울시. 별도 날씨 조회는 API 키 없이 이용할 수 있어요.", color=MUTED, size=9).grid(
            row=1, column=1, sticky="w"
        )

        form = tk.Frame(content, bg=PANEL)
        form.pack(fill="x", padx=12, pady=(9, 0))
        form.columnconfigure(1, weight=1)
        self.key = tk.StringVar(master=self)
        self.key_status = tk.StringVar(master=self)
        self.remove_key = tk.BooleanVar(master=self)
        self.model = tk.StringVar(master=self)
        self.request_limit = tk.StringVar(master=self)
        self.token_limit = tk.StringVar(master=self)
        self.budget = tk.StringVar(master=self)
        self.price = tk.StringVar(master=self)
        self.key_entry = _entry(form, self.key, show="*", exportselection=False)
        self._field(form, 0, "새 API 키", self.key_entry)
        _label(form, color=MUTED, size=9, textvariable=self.key_status).grid(row=1, column=1, sticky="w")
        self.remove_check = tk.Checkbutton(
            form, text="저장할 때 등록된 키 삭제", variable=self.remove_key, command=self._toggle_remove,
            font=_font(self, 9), fg=TEXT, bg=PANEL, activeforeground=TEXT, activebackground=PANEL,
            selectcolor=PANEL_2, bd=0, highlightthickness=0, cursor="hand2",
        )
        self.remove_check.grid(row=2, column=1, sticky="w", pady=(0, 5))
        ttk.Style(self).configure(
            "Assistant.TCombobox", fieldbackground=PANEL_2, background=PANEL_2, foreground=TEXT,
            arrowcolor=MUTED, bordercolor=BORDER,
        )
        model_entry = ttk.Combobox(
            form, textvariable=self.model, values=MODELS, font=_font(self), style="Assistant.TCombobox",
        )
        self._field(form, 3, "모델", model_entry)
        _label(form, color=MUTED, size=9, textvariable=self.price).grid(row=4, column=1, sticky="w", pady=(0, 4))
        self._field(form, 5, "하루 요청 한도", _entry(form, self.request_limit))
        self._field(form, 6, "하루 토큰 한도", _entry(form, self.token_limit))
        self._field(form, 7, "하루 추정 비용 한도 (USD)", _entry(form, self.budget))
        _label(form, "빈 칸은 해당 한도를 적용하지 않아요.", color=MUTED, size=9).grid(
            row=8, column=1, sticky="w"
        )
        self.model.trace_add("write", self._update_price)

        usage = tk.Frame(content, bg=PANEL_2, highlightthickness=1, highlightbackground=BORDER)
        usage.pack(fill="x", padx=12, pady=(12, 6))
        usage_header = tk.Frame(usage, bg=PANEL_2)
        usage_header.pack(fill="x", padx=8, pady=(5, 0))
        _label(usage_header, "오늘 앱 사용량", size=11).pack(side="left")
        _button(usage_header, "새로고침", self.refresh_usage).pack(side="right")
        self.usage = tk.StringVar(master=self)
        _label(usage, textvariable=self.usage).pack(fill="x", padx=8, pady=(1, 2))
        _label(
            usage, "비용은 추정치예요. 실제 청구액은 OpenAI 사용량 대시보드에서 확인해 주세요.",
            size=9, color=MUTED, wraplength=530,
        ).pack(fill="x", padx=8, pady=(0, 6))

    @staticmethod
    def _field(form, row, title, widget):
        _label(form, title).grid(row=row, column=0, sticky="w", padx=(0, 12), pady=3)
        widget.grid(row=row, column=1, sticky="ew", pady=3, ipady=3)

    def _toggle_remove(self):
        self.key_entry.configure(state="disabled" if self.remove_key.get() else "normal")
        if self.remove_key.get():
            self.key.set("")

    def _hide(self, _event=None):
        self.key.set("")
        return super()._hide()

    def _update_price(self, *_args):
        prices = MODEL_PRICES.get(self.model.get().strip())
        if prices is None:
            self.price.set("이 모델은 앱에서 비용을 추정할 수 없어요.")
            return
        self.price.set(
            f"100만 토큰 기본 요금 · 입력 ${prices.input_per_million:g} · "
            f"캐시 입력 ${prices.cached_input_per_million:g} · 출력 ${prices.output_per_million:g}"
        )

    def reload(self):
        self.key.set("")
        self.remove_key.set(False)
        self._toggle_remove()
        try:
            settings = self.service.load_settings()
            has_key = self.service.has_key()
        except Exception:
            self.status.set("AI 설정을 불러오지 못했어요.")
            self.save_button.configure(state="disabled")
            return
        self.enabled.set(settings.enabled)
        self.proactive.set(settings.proactive_enabled)
        self.memory.set(settings.memory_enabled)
        self.model.set(settings.model)
        self.request_limit.set("" if settings.daily_request_limit is None else str(settings.daily_request_limit))
        self.token_limit.set("" if settings.daily_token_limit is None else str(settings.daily_token_limit))
        self.budget.set("" if settings.daily_budget_usd is None else str(settings.daily_budget_usd))
        self.weather_location.set(settings.weather_location)
        storage = "Windows 보호 저장소에 보관" if self.service.persistent_key else "이번 실행 중에만 보관"
        self.key_status.set(f"{storage} · 빈 칸이면 기존 키 유지" if has_key else f"키 미등록 · {storage}")
        self.remove_check.configure(state="normal" if has_key else "disabled")
        self.save_button.configure(state="normal")
        self.status.set(self.service.settings_issue)

    def refresh_usage(self):
        try:
            usage = self.service.ledger.summary()
        except Exception:
            self.usage.set("사용량을 불러오지 못했어요.")
            return
        cost = "계산할 수 없음" if usage.estimated_cost_usd is None else f"${usage.estimated_cost_usd:,.6f} USD"
        unconfirmed = f"\n사용량 미확인 요청 {usage.unconfirmed_requests:,}회" if usage.unconfirmed_requests else ""
        self.usage.set(
            f"요청 {usage.requests:,}회 · 토큰 {usage.total_tokens:,}개\n"
            f"입력 {usage.input_tokens:,} · 출력 {usage.output_tokens:,} · 추정 비용 {cost}{unconfirmed}"
        )

    def _save(self):
        request_limit = self.request_limit.get().strip()
        token_limit = self.token_limit.get().strip()
        budget = self.budget.get().strip()
        try:
            settings = AISettings(
                enabled=self.enabled.get(), proactive_enabled=self.proactive.get(),
                memory_enabled=self.memory.get(), model=self.model.get().strip(),
                daily_request_limit=int(request_limit) if request_limit else None,
                daily_token_limit=int(token_limit) if token_limit else None,
                daily_budget_usd=float(budget) if budget else None,
                weather_location=self.weather_location.get().strip(),
            )
        except ValueError:
            self.status.set("요청·토큰 한도는 정수로, 비용 한도는 숫자로 입력해 주세요.")
            return
        try:
            settings.validate()
            self.service.save_settings(settings, new_key=self.key.get().strip() or None, remove_key=self.remove_key.get())
        except SettingsError as error:
            self.status.set(str(error))
            return
        except Exception:
            self.status.set("AI 설정을 저장하지 못했어요.")
            return
        self.reload()
        if not self.status.get():
            self.status.set("AI 설정을 저장했어요.")
        self.owner.settings_changed()
