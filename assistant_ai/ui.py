from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from queue import Empty, SimpleQueue
import re
from threading import Event, Thread
import tkinter as tk
from tkinter import messagebox, ttk
import tkinter.font as tkfont
from urllib.parse import urlsplit
import webbrowser
from uuid import uuid4

from app import AMBER, BG, BORDER, MUTED, PANEL, PANEL_2, PURPLE, PURPLE_2, TEXT
from app_brand import APP_NAME

from .api import AIError
from .config import SettingsError
from .ui_helpers import position_window


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
        relief="flat", bd=0, padx=10, pady=6, cursor="hand2", takefocus=True,
        highlightthickness=1, highlightbackground=BORDER, highlightcolor="#B9D6FF",
    )


def _entry(parent, variable, **options):
    return tk.Entry(
        parent, textvariable=variable, font=_font(parent), fg=TEXT, bg=PANEL_2,
        insertbackground=TEXT, relief="flat", highlightthickness=1,
        highlightbackground=BORDER, highlightcolor=PURPLE, **options,
    )


def _text(parent, **options):
    widget = tk.Text(
        parent, wrap="word", width=1, font=_font(parent), fg=TEXT, bg=PANEL_2,
        insertbackground=TEXT, relief="flat", highlightthickness=1,
        highlightbackground=BORDER, highlightcolor=PURPLE, padx=9, pady=7, **options,
    )
    widget.bind("<Tab>", lambda _event: _move_focus(widget, False))
    widget.bind("<Shift-Tab>", lambda _event: _move_focus(widget, True))
    widget.bind("<ISO_Left_Tab>", lambda _event: _move_focus(widget, True))
    return widget


def _move_focus(widget, backwards):
    target = widget.tk_focusPrev() if backwards else widget.tk_focusNext()
    if target is not None:
        target.focus_set()
    return "break"


def _usage_text(service):
    settings = service.load_settings()
    usage = service.ledger.summary(settings)
    cost = usage.estimated_cost_usd
    confirmed = "계산 불가" if cost is None else f"${cost:.4f}"
    reserved = getattr(usage, "reserved_cost_usd", 0)
    pending = "계산 불가" if reserved is None else f"${reserved:.4f}"
    remaining = getattr(usage, "remaining_budget_usd", None)
    allowance = "미설정" if settings.daily_budget_usd is None else ("계산 불가" if remaining is None else f"${remaining:.4f}")
    return f"{settings.model} · 오늘 기록 {confirmed} · 예약 {pending} · 남은 비용 한도 {allowance}"


def _add_scrollbar(frame, widget):
    bar = tk.Scrollbar(frame, command=widget.yview)
    widget.configure(yscrollcommand=bar.set)
    bar.pack(side="right", fill="y")
    widget.pack(side="left", fill="both", expand=True)


def _flow_buttons(parent, entries, *, columns=3):
    """Buttons wrap instead of disappearing on narrow/high-DPI windows."""
    frame = tk.Frame(parent, bg=parent.cget("bg"))
    buttons = [_button(frame, label, callback) for label, callback in entries]
    def arrange(event=None):
        available = event.width if event else max(1, frame.winfo_width())
        cell = max((button.winfo_reqwidth() for button in buttons), default=1) + 6
        count = max(1, min(columns, available // cell))
        for col in range(columns):
            frame.grid_columnconfigure(col, weight=1 if col < count else 0)
        for index, button in enumerate(buttons):
            button.grid(row=index // count, column=index % count, sticky="ew", padx=2, pady=2)
    frame.bind("<Configure>", arrange)
    arrange()
    return frame, buttons


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

    def open_picker(self):
        owner = self.widget.winfo_toplevel().owner
        window = _Window(owner, "출처 열기", 590, 330)
        _label(window.body, "출처를 선택하고 Enter를 누르면 브라우저에서 열어요.").pack(fill="x", padx=12, pady=10)
        entries = list(dict.fromkeys(self.targets.values()))
        listing = tk.Listbox(window.body, font=_font(window), bg=PANEL_2, fg=TEXT,
                             selectbackground=PURPLE, exportselection=False, takefocus=True)
        listing.pack(fill="both", expand=True, padx=12, pady=6)
        for url in entries:
            listing.insert("end", url)
        def open_selected(_event=None):
            selected = listing.curselection()
            if selected:
                _open_source(entries[selected[0]])
            return "break"
        listing.bind("<Return>", open_selected)
        _button(window.body, "브라우저에서 열기", open_selected).pack(pady=8)
        if entries:
            listing.selection_set(0)
        else:
            listing.insert("end", "이 답변에는 출처 링크가 없어요.")
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.bind("<Escape>", lambda _event: window.destroy())
        window._hide = lambda _event=None: window.destroy()
        window.show()
        listing.focus_set()

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

    def __init__(self, root, service, *, context, dispatch, on_chat_state=None, chat_work_area=None,
                 image_catalog=None, image_propose=None, image_apply=None, image_cancel=None,
                 image_undo=None, image_preview=None):
        self.root = root
        self.service = service
        self.context = context
        self.dispatch = dispatch
        self.on_chat_state = on_chat_state
        self.chat_work_area = chat_work_area
        self.image_catalog = image_catalog
        self.image_propose = image_propose
        self.image_apply = image_apply
        self.image_cancel = image_cancel
        self.image_undo = image_undo
        self.image_preview = image_preview
        self._extra_windows = []
        self._background_jobs = {}
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
        self._poll_id = None
        self._cancel = None
        self._results = SimpleQueue()
        self._closed = False
        self._sent_text = ""
        self._previous_turns = []
        self._history_limit = HISTORY_PAGE_SIZE
        self._chat_state = ("idle", "")
        self._request_id = None
        self._failed_request = None
        self._editing_retry_id = None

    def run_background(self, operation, done):
        """Workers never call Tk; all completions are delivered by the root loop."""
        queue = SimpleQueue()
        token = uuid4().hex
        def work():
            try:
                queue.put((operation(), None))
            except Exception as error:
                queue.put((None, error))
        def poll():
            self._background_jobs.pop(token, None)
            if self._closed:
                return
            try:
                value, error = queue.get_nowait()
            except Empty:
                self._background_jobs[token] = self.root.after(70, poll)
            else:
                done(value, error)
        Thread(target=work, daemon=True).start()
        self._background_jobs[token] = self.root.after(70, poll)

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
        width, height = self.chat_window._preferred_size
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
            from .ui_memory import _MemoryWindow
            self.memory_window = _MemoryWindow(self)
        self.memory_window.refresh()
        self.memory_window.show()
        self.memory_window.search_entry.focus_set()

    def open_settings(self):
        if self._closed:
            return
        if self.settings_window is None:
            from .ui_settings import _SettingsWindow
            self.settings_window = _SettingsWindow(self)
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

    def open_weather(self, place=None):
        if self._closed:
            return
        if self.weather_window is None:
            self.weather_window = _WeatherWindow(self)
        self.weather_window.show()
        if place:
            self.weather_window.region.set(place)
        if place or not self.weather_window.loaded:
            self.weather_window.lookup()

    def open_today(self):
        try:
            text = self.service.local_status(self.context())
        except Exception:
            text = "현재 타이머 상태를 불러오지 못했어요. 잠시 뒤 다시 확인해 주세요."
        self.open_reply(text)

    def quiet_today(self):
        quiet = self.service.load_settings().proactive_quiet_until == datetime.now().date().isoformat()
        self.service.quiet_today(not quiet)
        if self.chat_window is not None:
            self.chat_window.refresh_summary()
            self.chat_window.status.set("오늘 AI 안내를 다시 켰어요." if quiet else "오늘은 AI가 먼저 말하지 않아요. 타이머 알림은 그대로예요.")

    def open_image_picker(self):
        if self.image_catalog is None or self.image_propose is None:
            self.open_reply("이미지 선택은 타이머 설정의 이미지 화면에서 사용할 수 있어요.")
            return
        window = _ImagePickerWindow(self)
        window.show()

    def show_image_proposal(self, proposal):
        window = _Window(self, "이미지 변경 확인", 680, 700)
        title = _label(window.body, proposal.get("summary", "이미지 변경"), size=13, wraplength=480)
        title.pack(fill="x", padx=14, pady=(12, 6))
        title.bind("<Configure>", lambda event: title.configure(wraplength=event.width))
        _label(window.body, proposal.get("scope", ""), color=MUTED, wraplength=480).pack(fill="x", padx=14)
        previews = tk.Frame(window.body, bg=PANEL)
        previews.pack(fill="both", expand=True, padx=12, pady=8)
        previews.columnconfigure(0, weight=1, uniform="images")
        previews.columnconfigure(1, weight=1, uniform="images")
        previews.rowconfigure(1, weight=1)
        for column, prefix, default_label in ((0, "before", "현재 이미지"), (1, "after", "변경 이미지")):
            label = proposal.get(f"{prefix}_preview_label", default_label)
            heading = _label(previews, label, size=10, wraplength=280)
            heading.grid(row=0, column=column, sticky="ew", padx=5, pady=5)
            heading.bind("<Configure>", lambda event, target=heading: target.configure(wraplength=max(80, event.width)))
            preview = tk.Label(previews, bg=PANEL_2, fg=MUTED, width=1, height=1, text="미리보기 없음", wraplength=250)
            preview.grid(row=1, column=column, sticky="nsew", padx=5)
            ref = proposal.get(f"{prefix}_preview_ref") or (proposal.get("preview_ref") if prefix == "after" else None)
            if ref and self.image_preview:
                try:
                    from PIL import Image, ImageTk
                    path = self.image_preview(ref)
                    if path:
                        with Image.open(path) as source:
                            preview._source_image = source.convert("RGBA")
                        def render(event, target=preview):
                            picture = target._source_image.copy()
                            picture.thumbnail((max(1, event.width - 12), max(1, event.height - 12)), Image.Resampling.LANCZOS)
                            target.image = ImageTk.PhotoImage(picture)
                            target.configure(image=target.image, text="")
                        preview.bind("<Configure>", render)
                except Exception:
                    preview.configure(text="미리보기를 표시할 수 없어요.")
        state = {"pending": proposal.get("status") == "pending"}
        status = tk.StringVar(master=window)
        _label(window.body, textvariable=status, color=AMBER, wraplength=480).pack(fill="x", padx=14, pady=6)
        controls = tk.Frame(window.body, bg=PANEL)
        controls.pack(side="bottom", fill="x", padx=14, pady=12)
        def cancel():
            if state["pending"] and self.image_cancel:
                self.image_cancel(proposal["id"])
                state["pending"] = False
            window.withdraw()
        def apply():
            if not state["pending"] or self.image_apply is None:
                return
            result = self.image_apply(proposal["id"])
            status.set(result.get("summary", "변경 결과를 확인해 주세요."))
            state["pending"] = False
            apply_button.configure(state="disabled")
            undo_button.configure(state="normal" if result.get("changed") else "disabled")
            cancel_button.configure(text="닫기")
        def undo():
            result = self.image_undo() if self.image_undo else {"summary": "되돌릴 변경이 없어요."}
            status.set(result.get("summary", "되돌리기 결과를 확인해 주세요."))
            undo_button.configure(state="disabled")
        apply_button = _button(controls, "적용", apply, primary=True)
        apply_button.pack(side="right")
        cancel_button = _button(controls, "취소", cancel)
        cancel_button.pack(side="right", padx=6)
        undo_button = _button(controls, "되돌리기", undo)
        undo_button.pack(side="left")
        undo_button.configure(state="disabled")
        if not state["pending"]:
            apply_button.configure(state="disabled")
            status.set(proposal.get("summary", "이 요청을 적용할 수 없어요."))
        window.protocol("WM_DELETE_WINDOW", cancel)
        window.bind("<Escape>", lambda _event: cancel())
        window._hide = lambda _event=None: cancel()
        window.show()
        cancel_button.focus_set()

    def open_weather_settings(self):
        if not self._closed:
            self.open_settings()
            self.settings_window.focus_weather()

    def close(self):
        if self._closed:
            return
        self._closed = True
        if self._cancel is not None:
            self._cancel.set()
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        for event in self._background_jobs.values():
            self.root.after_cancel(event)
        self._background_jobs.clear()
        self._set_chat_state("idle")
        for window in (self.chat_window, self.memory_window, self.settings_window, self.reply_window, self.weather_window):
            if window is not None:
                window.destroy()
        for window in self._extra_windows:
            if window.winfo_exists():
                window.destroy()

    def hide(self):
        self.cancel()
        for window in self._extra_windows:
            if window.winfo_exists():
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
        for window in (self.chat_window, self.reply_window, self.weather_window):
            if window is not None:
                window.apply_reading_size()

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

    def send(self, text=None, *, retry_of=None):
        if self._cancel is not None:
            return
        text = self.chat_window.input.get("1.0", "end-1c").strip() if text is None else text.strip()
        if not text:
            self.chat_window.status.set("보낼 메시지를 입력해 주세요.")
            return
        if text in {"/오늘", "/상태"}:
            self.open_today()
            return
        if text.startswith("/날씨"):
            place = text[3:].strip()
            self.open_weather(place=place or None)
            return
        if text == "/이미지":
            self.open_image_picker()
            return
        if not self.chat_window.update_availability():
            return
        if retry_of is None and self._failed_request is not None:
            failed_id, failed_text = self._failed_request
            if text == failed_text or self._editing_retry_id == failed_id:
                retry_of = failed_id
        self._editing_retry_id = None
        try:
            context = self.context()
        except Exception:
            self.chat_window.status.set("타이머 상태를 확인하지 못했어요. 다시 시도해 주세요.")
            self._set_chat_state("error")
            return
        self._previous_turns = self._render_history(pending=text)
        self._sent_text = text
        request_id = uuid4().hex
        self._request_id = request_id
        self._cancel = Event()
        self.chat_window.input.delete("1.0", "end")
        self.chat_window.input.edit_modified(False)
        self.chat_window.set_retry_available(False)
        self.chat_window.set_busy(True)
        activity = getattr(self.service, "request_activity", lambda _text: "승아가 답을 준비하고 있어요…")(text)
        self.chat_window.status.set(activity + " 창을 숨겨도 답변은 계속 받아요.")
        Thread(target=self._request, args=(request_id, text, context, self._cancel, retry_of), daemon=True).start()
        self._poll_id = self.root.after(60, self._poll)
        self._set_chat_state("waiting")

    def _request(self, request_id, text, context, cancel, retry_of=None):
        try:
            reply = self.service.chat(text, context=context, dispatch=self.dispatch, cancel=cancel,
                                      request_id=request_id, retry_of=retry_of)
        except (AIError, SettingsError) as error:
            self._results.put((request_id, None, str(error)))
        except Exception:
            self._results.put((request_id, None, "대화 중 문제가 생겼어요. 다시 시도해 주세요."))
        else:
            self._results.put((request_id, reply, ""))

    def _poll(self):
        self._poll_id = None
        if self._closed or self._request_id is None:
            return
        if self._cancel is not None and self._cancel.is_set():
            self.cancel()
            return
        while True:
            try:
                request_id, reply, error = self._results.get_nowait()
            except Empty:
                self._poll_id = self.root.after(60, self._poll)
                return
            if request_id == self._request_id:
                break
        sent = self._sent_text
        self._request_id = None
        self._cancel = None
        self.chat_window.set_busy(False)
        self.chat_window.update_availability()
        turns = self._render_history()
        if reply and turns is None:
            self.chat_window.render([], pending=sent, reply=reply)
        if error:
            self._failed_request = (request_id, sent)
            if not self.chat_window.input.get("1.0", "end-1c").strip():
                self.chat_window.input.insert("1.0", sent)
                self.chat_window.input.edit_modified(False)
            self.chat_window.set_retry_available(True)
            receipts = self.service.action_receipts(request_id)
            detail = " 이미 적용된 앱 변경은 유지돼요. 재시도는 같은 변경을 다시 실행하지 않아요." if receipts else ""
            self.chat_window.status.set(error + detail)
        else:
            self._failed_request = None
        self._sent_text = ""
        self._previous_turns = []
        self._set_chat_state("reply", reply) if reply else self._set_chat_state("error")
        if self.settings_window is not None:
            self.settings_window.refresh_usage()
        self.chat_window.refresh_summary()
        if reply and self.memory_window is not None and self.memory_window.winfo_viewable():
            self.memory_window.refresh()

    def retry(self, *, edit=False):
        if self._failed_request is None or self._cancel is not None:
            return
        request_id, text = self._failed_request
        if edit:
            self._editing_retry_id = request_id
            current = self.chat_window.input.get("1.0", "end-1c").strip()
            if current and current != text:
                self.chat_window.status.set("작성 중인 초안을 보존했어요. 보내기를 누르면 새 메시지로 전송해요.")
            else:
                self.chat_window.input.delete("1.0", "end")
                self.chat_window.input.insert("1.0", text)
                self.chat_window.status.set("내용을 수정한 뒤 보내기를 눌러 주세요.")
            self.chat_window.input.focus_set()
        else:
            draft = self.chat_window.input.get("1.0", "end-1c").strip()
            if draft and draft != text:
                self.chat_window.status.set("새 초안이 있어요. 내용을 보존하려면 먼저 보내거나 복사해 주세요.")
                return
            self.send(text, retry_of=request_id)

    def cancel(self):
        cancel = self._cancel
        if cancel is None:
            return
        request_id, sent = self._request_id, self._sent_text
        self.service.cancel_chat(cancel)
        cancel.set()
        self._request_id = None
        self._cancel = None
        if self._poll_id is not None:
            self.root.after_cancel(self._poll_id)
            self._poll_id = None
        self._failed_request = (request_id, sent)
        self._sent_text = ""
        if self.chat_window is not None:
            self.chat_window.set_busy(False)
            self.chat_window.update_availability()
            self.chat_window.set_retry_available(True)
            self._render_history()
            if not self.chat_window.input.get("1.0", "end-1c").strip():
                self.chat_window.input.insert("1.0", sent)
                self.chat_window.input.edit_modified(False)
            self.chat_window.status.set("응답을 취소했어요. 새 메시지를 보낼 수 있어요. 이미 적용된 변경과 서버 사용량은 유지될 수 있어요.")
        self._set_chat_state("idle")

    def clear_history(self):
        if self._cancel is not None:
            return
        try:
            counts = self.service.history_counts()
            detail = f"저장된 대화 {counts.get('conversation_turns', 0):,}개와 이번 실행의 대화 {counts.get('session_turns', 0):,}개를 지울까요?\n두 집계에는 같은 대화가 포함될 수 있어요. 장기 기억 {counts.get('memories', 0):,}개는 유지해요."
        except Exception:
            detail = "저장된 대화와 이번 실행 중의 대화를 모두 지울까요? 장기 기억은 유지해요."
        if not messagebox.askyesno(
            "대화 기록 지우기", detail,
            parent=self.chat_window,
        ):
            return
        try:
            self.service.clear_history()
        except Exception:
            self.chat_window.status.set("대화 기록을 지우지 못했어요.")
            return
        self._history_limit = HISTORY_PAGE_SIZE
        self._failed_request = None
        self._editing_retry_id = None
        self.chat_window.set_retry_available(False)
        if self._render_history() is not None:
            self.chat_window.status.set("대화 기록을 지웠어요.")
        self._set_chat_state("idle")


class _Window(tk.Toplevel):
    def __init__(self, owner, title, width, height):
        super().__init__(owner.root, bg=BG)
        self.owner = owner
        self.service = owner.service
        self.font_family = owner.font_family
        self._preferred_size = (width, height)
        self.withdraw()
        self.title(f"{title} | {APP_NAME}")
        self.geometry(f"{width}x{height}")
        self.protocol("WM_DELETE_WINDOW", self._hide)
        self.bind("<Escape>", self._hide)
        self.body = tk.Frame(self, bg=PANEL)
        self.body.pack(fill="both", expand=True, padx=12, pady=12)
        self._reading_widgets = []
        owner._extra_windows.append(self)
        self.bind("<Control-plus>", lambda _event: self.change_reading_size(1))
        self.bind("<Control-equal>", lambda _event: self.change_reading_size(1))
        self.bind("<Control-minus>", lambda _event: self.change_reading_size(-1))

    def _hide(self, _event=None):
        self.withdraw()
        return "break"

    def show(self):
        position_window(self, self.owner.root, self.owner.chat_work_area)
        self.deiconify()
        self.lift()

    def apply_reading_size(self):
        size = getattr(self.service.load_settings(), "reading_text_size", 12)
        for widget in self._reading_widgets:
            gap = max(1, round(tkfont.Font(root=self, family=self.font_family, size=size).metrics("linespace") * .25))
            widget.configure(font=(self.font_family, size), spacing2=gap, spacing3=gap)

    def change_reading_size(self, delta):
        settings = self.service.load_settings()
        size = min(20, max(10, getattr(settings, "reading_text_size", 12) + delta))
        try:
            self.service.save_settings(replace(settings, reading_text_size=size))
        except Exception:
            return "break"
        self.owner.settings_changed()
        return "break"

    def copy_text(self, widget):
        text = widget.get("1.0", "end-1c")
        self.clipboard_clear()
        self.clipboard_append(text)

    def reading_controls(self, parent, widget, sources=None):
        _button(parent, "글자 −", lambda: self.change_reading_size(-1)).pack(side="left", padx=2)
        _button(parent, "글자 +", lambda: self.change_reading_size(1)).pack(side="left", padx=2)
        _button(parent, "복사", lambda: self.copy_text(widget)).pack(side="left", padx=2)
        if sources is not None:
            _button(parent, "출처 열기", sources.open_picker).pack(side="left", padx=2)


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
        self._reading_widgets.append(self.text)
        toolbar = tk.Frame(self.body, bg=PANEL)
        toolbar.pack(side="bottom", fill="x", padx=12, pady=3, before=self.actions)
        self.reading_controls(toolbar, self.text, self._sources)
        self.apply_reading_size()

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


class _ImagePickerWindow(_Window):
    def __init__(self, owner):
        super().__init__(owner, "이미지 선택 · AI 키 없이 사용", 650, 520)
        self.catalog = owner.image_catalog()
        self.roles = self.catalog.get("roles", [])
        self.sets = self.catalog.get("sets", [])
        self.images = self.catalog.get("images", [])
        _label(self.body, "전체 세트 또는 한 상황의 이미지를 골라 주세요.", size=12).pack(fill="x", padx=12, pady=12)
        set_row = tk.Frame(self.body, bg=PANEL)
        set_row.pack(fill="x", padx=12, pady=5)
        _label(set_row, "전체 세트").pack(side="left", padx=(0, 8))
        self.set_choice = ttk.Combobox(set_row, state="readonly", values=[item["label"] for item in self.sets], font=_font(self))
        self.set_choice.pack(side="left", fill="x", expand=True)
        if self.sets:
            self.set_choice.current(0)
        _button(set_row, "변경 미리보기", self.choose_set).pack(side="right", padx=5)
        role_row = tk.Frame(self.body, bg=PANEL)
        role_row.pack(fill="x", padx=12, pady=6)
        _label(role_row, "상황").pack(side="left", padx=(0, 8))
        self.role_choice = ttk.Combobox(role_row, state="readonly", values=[item["label"] for item in self.roles], font=_font(self))
        self.role_choice.pack(side="left", fill="x", expand=True)
        self.role_choice.bind("<<ComboboxSelected>>", self.filter_images)
        if self.roles:
            self.role_choice.current(0)
        _button(role_row, "세트 따라가기", self.follow).pack(side="right", padx=5)
        frame = tk.Frame(self.body, bg=PANEL)
        frame.pack(fill="both", expand=True, padx=12, pady=5)
        self.listing = tk.Listbox(frame, bg=PANEL_2, fg=TEXT, selectbackground=PURPLE,
                                 exportselection=False, font=_font(self), activestyle="dotbox")
        _add_scrollbar(frame, self.listing)
        self.listing.bind("<Return>", self.choose_image)
        self.listing.bind("<Double-Button-1>", self.choose_image)
        footer, _ = _flow_buttons(self.body, [("선택 이미지 미리보기", self.choose_image),
                                              ("직전 이미지 변경 되돌리기", self.undo)])
        footer.pack(fill="x", padx=10, pady=8)
        self.filter_images()

    def role_id(self):
        index = self.role_choice.current()
        return self.roles[index]["id"] if index >= 0 else "default"

    def filter_images(self, _event=None):
        self.visible = [item for item in self.images if item.get("role") == self.role_id()]
        self.listing.delete(0, "end")
        for item in self.visible:
            self.listing.insert("end", item["label"])
        if self.visible:
            self.listing.selection_set(0)

    def propose(self, action):
        self.owner.show_image_proposal(self.owner.image_propose(action))

    def choose_set(self):
        index = self.set_choice.current()
        if index >= 0:
            self.propose({"kind": "base_set", "set_id": self.sets[index]["id"]})

    def choose_image(self, _event=None):
        selected = self.listing.curselection()
        if selected:
            self.propose({"kind": "image", "role": self.role_id(), "ref": self.visible[selected[0]]["ref"]})
        return "break"

    def follow(self):
        self.propose({"kind": "follow", "role": self.role_id()})

    def undo(self):
        if self.owner.image_undo:
            self.owner.open_reply(self.owner.image_undo().get("summary", "변경 결과를 확인해 주세요."))


class _WeatherWindow(_ReadoutWindow):
    def __init__(self, owner):
        super().__init__(owner, "날씨 조회 · AI 키 없이 사용")
        self.loaded = False
        self.busy = False
        self.region = tk.StringVar(master=self, value=self.service.load_settings().weather_location)
        row = tk.Frame(self.body, bg=PANEL)
        row.pack(fill="x", padx=14, pady=6, before=self.text.master)
        _label(row, "지역").pack(side="left", padx=(0, 6))
        entry = _entry(row, self.region)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _event: self.lookup())
        self.lookup_button = _button(row, "조회", self.lookup, primary=True)
        self.lookup_button.pack(side="left", padx=5)
        _button(row, "기본 지역으로", self.save_region).pack(side="left")

    def lookup(self):
        if self.busy:
            return
        place = self.region.get().strip()
        if not place:
            self.set_text("조회할 지역을 입력해 주세요. 예: 세종시, 대전시")
            return
        self.busy = True
        self.lookup_button.configure(state="disabled")
        self.set_text(f"{place}의 기상정보를 조회하고 있어요…")
        def done(value, error):
            if not self.winfo_exists():
                return
            self.busy = False
            self.lookup_button.configure(state="normal")
            self.loaded = True
            self.set_text(str(error) if error else value)
        self.owner.run_background(lambda: self.service.weather_report(place), done)

    def save_region(self):
        try:
            self.service.save_settings(replace(self.service.load_settings(), weather_location=self.region.get().strip()))
        except (SettingsError, ValueError) as error:
            self.set_text(str(error))
        else:
            self.set_text(f"기본 날씨 지역을 {self.region.get().strip()}로 저장했어요. 조회를 누르면 날씨를 확인해요.")


class _ChatWindow(_Window):
    DEFAULT_SIZE = (720, 780)
    MIN_SIZE = (500, 420)

    def __init__(self, owner):
        dpi_scale = owner.root.winfo_fpixels("1i") / 96
        width = round(self.DEFAULT_SIZE[0] * min(1.5, max(1, dpi_scale)))
        super().__init__(owner, "승아와 대화", width, self.DEFAULT_SIZE[1])
        self.minsize(*self.MIN_SIZE)
        header = tk.Frame(self.body, bg=PANEL)
        header.pack(fill="x", padx=12, pady=(10, 4))
        _label(header, "승아와 대화", size=15).pack(side="left")
        _button(header, "AI 설정", owner.open_settings).pack(side="right")
        menu_button = tk.Menubutton(header, text="도구 ▾", font=_font(self, 10), bg=PANEL_2, fg=TEXT,
                                    activebackground=BORDER, activeforeground=TEXT, relief="flat", takefocus=True,
                                    padx=10, pady=6, highlightthickness=1, highlightcolor="#B9D6FF")
        self.tools_menu = tk.Menu(menu_button, tearoff=False)
        for label, command in [
            ("오늘 상태 · 무료", owner.open_today), ("날씨 · 무료", owner.open_weather),
            ("이미지 선택", owner.open_image_picker), ("기억 관리", owner.open_memories),
            ("오늘 AI 안내 끄기", owner.quiet_today),
        ]:
            self.tools_menu.add_command(label=label, command=command)
        self.tools_menu.add_command(label="전송·저장 안내", command=lambda: owner.open_reply(self.privacy.get()))
        menu_button.configure(menu=self.tools_menu)
        menu_button.pack(side="right", padx=6)
        self.summary = tk.StringVar(master=self)
        summary = _label(self.body, textvariable=self.summary, size=9, color=MUTED, wraplength=620)
        summary.pack(fill="x", padx=12, pady=3)
        summary.bind("<Configure>", lambda event: summary.configure(wraplength=event.width))
        self.privacy = tk.StringVar(master=self)
        self.privacy_brief = tk.StringVar(master=self)
        privacy = _label(self.body, color=MUTED, textvariable=self.privacy_brief, size=9, wraplength=580)
        privacy.pack(fill="x", padx=12, pady=(0, 7))
        privacy.bind("<Configure>", lambda event: privacy.configure(wraplength=event.width))

        history_frame = tk.Frame(self.body, bg=PANEL)
        self.history = _text(history_frame, height=4, state="disabled")
        self.history.tag_configure("user", foreground="#C4B5FD", spacing1=6)
        self.history.tag_configure("assistant", foreground="#86EFAC", spacing1=6)
        self.history.tag_configure("note", foreground=MUTED)
        self._sources = _SourceLinks(self.history)
        _add_scrollbar(history_frame, self.history)
        self._reading_widgets.append(self.history)

        composer = tk.Frame(self.body, bg=PANEL)
        composer.pack(side="bottom", fill="x")
        _label(composer, "메시지 · Ctrl+Enter로 보내기", color=MUTED, size=9).pack(
            anchor="w", padx=12, pady=(8, 3)
        )
        input_frame = tk.Frame(composer, bg=PANEL)
        input_frame.pack(fill="x", padx=12)
        self.input = _text(input_frame, height=1 if dpi_scale >= 1.5 else 2, undo=True)
        self._reading_widgets.append(self.input)
        _add_scrollbar(input_frame, self.input)
        self.input.bind("<Control-Return>", self._send_from_keyboard)
        self.input.bind("<<Modified>>", self._input_modified)
        self.input_count = tk.StringVar(master=self, value="0자 · Tab으로 버튼 이동")
        _label(composer, textvariable=self.input_count, color=MUTED, size=9).pack(anchor="w", padx=12)
        self.status = tk.StringVar(master=self)
        status = _label(composer, color=AMBER, textvariable=self.status, wraplength=580)
        status.pack(fill="x", padx=12, pady=(5, 0))
        status.bind("<Configure>", lambda event: status.configure(wraplength=event.width))

        controls = tk.Frame(composer, bg=PANEL)
        controls.pack(fill="x", padx=12, pady=(4, 10))
        self.clear_button = _button(controls, "기록 지우기", owner.clear_history)
        self.clear_button.pack(side="left")
        self.older_button = _button(controls, "이전 대화", owner.show_older)
        self.older_button.pack(side="left", padx=(6, 0))
        self.send_button = _button(controls, "보내기", owner.send, primary=True)
        self.send_button.pack(side="right")
        self.cancel_button = _button(controls, "응답 취소", owner.cancel)
        self.cancel_button.pack(side="right", padx=(0, 6))
        retry_row = tk.Frame(composer, bg=PANEL)
        retry_row.pack(fill="x", padx=12, pady=(0, 4))
        self.retry_button = _button(retry_row, "재시도", owner.retry)
        self.retry_button.pack(side="left")
        self.edit_retry_button = _button(retry_row, "실패한 메시지 수정", lambda: owner.retry(edit=True))
        self.edit_retry_button.pack(side="left", padx=5)
        self.retry_row = retry_row
        self.set_retry_available(False)
        toolbar = tk.Frame(self.body, bg=PANEL)
        toolbar.pack(fill="x", padx=10, pady=3)
        reading_button = tk.Menubutton(toolbar, text="글자·복사·출처 ▾", font=_font(self, 9),
                                       bg=PANEL_2, fg=TEXT, padx=8, pady=5, takefocus=True)
        reading_menu = tk.Menu(reading_button, tearoff=False)
        for label, callback in [("글자 크게", lambda: self.change_reading_size(1)),
                                ("글자 작게", lambda: self.change_reading_size(-1)),
                                ("대화 복사", lambda: self.copy_text(self.history)),
                                ("출처 열기", self._sources.open_picker)]:
            reading_menu.add_command(label=label, command=callback)
        reading_button.configure(menu=reading_menu)
        reading_button.pack(side="left")
        self.web_enabled = tk.BooleanVar(master=self, value=self.service.load_settings().web_search_enabled)
        self.web_check = tk.Checkbutton(toolbar, text="웹 검색", variable=self.web_enabled,
                                       command=self._toggle_web, font=_font(self, 9), bg=PANEL, fg=TEXT,
                                       selectcolor=PANEL_2, activebackground=PANEL, activeforeground=TEXT)
        self.web_check.pack(side="right")
        self.has_older = False
        self.set_busy(False)
        history_frame.pack(fill="both", expand=True, padx=12)
        self.apply_reading_size()
        self.refresh_summary()

    def _hide(self, _event=None):
        if self.owner._cancel is None:
            self.owner._set_chat_state("idle")
        return super()._hide()

    def _toggle_web(self):
        try:
            self.service.save_settings(replace(self.service.load_settings(), web_search_enabled=self.web_enabled.get()))
        except Exception:
            self.status.set("웹 검색 설정을 저장하지 못했어요.")
        self.refresh_summary()

    def refresh_summary(self):
        try:
            self.summary.set(_usage_text(self.service))
            settings = self.service.load_settings()
            self.web_enabled.set(settings.web_search_enabled)
            quiet = settings.proactive_quiet_until == datetime.now().date().isoformat()
            self.tools_menu.entryconfigure(4, label="오늘 AI 안내 다시 켜기" if quiet else "오늘 AI 안내 끄기")
        except Exception:
            self.summary.set("사용량을 확인하려면 AI 설정을 열어 주세요.")

    def set_retry_available(self, available):
        if available:
            self.retry_row.pack(fill="x", padx=12, pady=(0, 4))
        else:
            self.retry_row.pack_forget()
        for button in (self.retry_button, self.edit_retry_button):
            button.configure(state="normal" if available else "disabled")

    def _send_from_keyboard(self, _event):
        self.owner.send()
        return "break"

    def _input_modified(self, _event):
        if self.input.edit_modified():
            self.input.edit_modified(False)
            size = len(self.input.get("1.0", "end-1c"))
            hint = " · 긴 메시지는 입력 비용이 늘 수 있어요" if size > 4000 else " · Tab으로 버튼 이동"
            self.input_count.set(f"{size:,}자{hint}")
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
        storage = "대화가 이 PC에 저장돼요." if settings.conversation_storage_enabled else "새 대화는 이번 실행 중에만 남아요."
        self.privacy.set(
            f"보낸 메시지, 관련 대화·기억, 타이머 상태가 OpenAI API에 전달될 수 있어요. {storage}"
        )
        self.privacy_brief.set("OpenAI API 사용 · " + storage + " · 자세한 안내는 도구 메뉴")
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
        if hasattr(self, "web_check"):
            self.web_check.configure(state="disabled" if busy else "normal")

    def update_older_button(self):
        can_page = self.has_older and self.owner._cancel is None
        self.older_button.configure(state="normal" if can_page else "disabled")

    def render(self, turns, *, pending="", reply=""):
        self.history.configure(state="normal")
        self.history.delete("1.0", "end")
        self._sources.clear()
        if not turns and not pending:
            self.history.insert("end", "승아에게 필요한 일을 물어보세요.\n\n처음이라면 ‘AI 연결 설정’에서 AI 사용과 API 키를 설정해 주세요.\n오늘 상태·날씨·이미지 선택은 AI 키 없이 사용할 수 있어요.\n\n예시: ‘오늘 얼마나 집중했어?’ · ‘휴식 간격을 50분으로 바꿔 줘’\n/오늘 · /날씨 세종시 · /이미지\n\nCtrl+Enter 보내기 · Tab 버튼 이동 · Ctrl+＋/－ 글자 크기\n", "note")
        for turn in turns:
            timestamp = _local_time(turn.created_at)
            sender = f"나 · {timestamp}" if timestamp else "나"
            self._write(sender, turn.user, "user")
            state = getattr(turn, "status", "completed" if turn.assistant is not None else "interrupted")
            if state != "completed":
                badge = {"pending": "응답 준비 중", "failed": "응답 실패", "cancelled": "취소됨", "interrupted": "중단됨"}.get(state, "응답 없음")
                self.history.insert("end", f"[{badge}]\n", "note")
            if turn.assistant is None:
                self.history.insert("end", "\n", "note")
            else:
                self._write("승아", turn.assistant, "assistant")
        if pending:
            self._write("나", pending, "user")
            if reply:
                self._write("승아", reply, "assistant")
            else:
                self.history.insert("end", "응답을 기다리는 중…\n", "note")
        self.history.configure(state="disabled")
        self.history.see("end" if turns or pending else "1.0")

    def _write(self, sender, text, tag):
        self.history.insert("end", f"{sender}\n", tag)
        if tag == "assistant":
            self._sources.insert(text)
        else:
            self.history.insert("end", text)
        self.history.insert("end", "\n\n")
