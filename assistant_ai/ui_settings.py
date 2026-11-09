from __future__ import annotations

from dataclasses import replace
from datetime import date
from threading import Event
import tkinter as tk
from tkinter import ttk

from app import AMBER, BORDER, MUTED, PANEL, PANEL_2, PURPLE, TEXT

from .config import MODEL_DESCRIPTIONS, MODEL_PRICES, MODEL_REASONING_EFFORT, MODELS, PROACTIVE_EVENTS, SettingsError
from .ui import _Window, _label, _button, _entry, _add_scrollbar, _font, _usage_text


_EVENT_LABELS = {
    "rest": "휴식 알림", "break_started": "휴식 시작", "away": "자리비움",
    "return": "복귀", "leave": "퇴근 안내", "periodic": "정기 응원",
}


class _SettingsWindow(_Window):
    """Keep an in-memory settings draft until Save or Discard is chosen."""

    def __init__(self, owner):
        super().__init__(owner, "AI·API 설정", 690, 690)
        self.minsize(510, 420)
        self._loading = False
        self._baseline = None
        self._base_settings = None
        self._test_cancel = None
        self.status = tk.StringVar(master=self)
        self.draft_status = tk.StringVar(master=self)
        self._vars = []

        footer = tk.Frame(self.body, bg=PANEL)
        footer.pack(side="bottom", fill="x", padx=12, pady=(6, 10))
        self._wrapped(footer, variable=self.status, color=AMBER).pack(fill="x", pady=(0, 3))
        self._wrapped(footer, variable=self.draft_status, color=MUTED, size=9).pack(fill="x")
        buttons = tk.Frame(footer, bg=PANEL)
        buttons.pack(fill="x", pady=(5, 0))
        self.discard_button = _button(buttons, "변경 버리기", self.reload)
        self.discard_button.pack(side="left")
        _button(buttons, "닫기 · 초안 유지", self._hide).pack(side="left", padx=5)
        self.save_button = _button(buttons, "설정 저장", self._save, primary=True)
        self.save_button.pack(side="right")

        self.canvas = tk.Canvas(self.body, bg=PANEL, highlightthickness=0, bd=0)
        _add_scrollbar(self.body, self.canvas)
        self.content = tk.Frame(self.canvas, bg=PANEL)
        window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda event: self.canvas.itemconfigure(window, width=event.width))
        self.bind("<MouseWheel>", self._scroll, add="+")
        self.bind("<Button-4>", lambda _e: self.canvas.yview_scroll(-3, "units"), add="+")
        self.bind("<Button-5>", lambda _e: self.canvas.yview_scroll(3, "units"), add="+")
        self.bind("<FocusIn>", self._focus_visible, add="+")
        self.bind("<Control-s>", lambda _e: self._save(), add="+")

        content = self.content
        _label(content, "승아 연결하기", size=15).pack(anchor="w", padx=12, pady=(10, 4))
        self._wrapped(content, "OpenAI API는 ChatGPT 구독과 별도 요금이에요. 키와 모델을 정한 뒤 저장해 주세요.", color=MUTED).pack(fill="x", padx=12, pady=(0, 8))
        self.enabled = self._variable(tk.BooleanVar)
        self._check(content, self.enabled, "승아의 AI 대화 사용").pack(anchor="w", padx=12, pady=3)
        self.proactive = self._variable(tk.BooleanVar)
        self._check(content, self.proactive, "승아가 상황에 맞춰 먼저 말 걸기").pack(anchor="w", padx=12, pady=3)
        self._wrapped(content, "켜면 휴식·복귀·업무 마무리를 살펴 먼저 말 걸어요. 사용 중 정기 대화는 기본 20분 간격이며, 대화 중·작성 중이거나 최근 5분 안에 대화했다면 쉬어요. API 사용량이 생기며 간격·상황은 고급 설정에서 바꿀 수 있어요.", color=MUTED, size=9).pack(fill="x", padx=12, pady=(0, 6))
        form = tk.Frame(content, bg=PANEL)
        form.pack(fill="x", padx=12, pady=5)
        form.columnconfigure(0, weight=1)
        self.key = self._variable()
        self.key_status = tk.StringVar(master=self)
        self.remove_key = self._variable(tk.BooleanVar)
        self.key_persistence = self._variable(value="session")
        self.model = self._variable()
        self.price = tk.StringVar(master=self)
        self.key_entry = _entry(form, self.key, show="*", exportselection=False)
        self._field(form, 0, "1. API 키 · 빈 칸은 기존 키 유지", self.key_entry)
        self._wrapped(form, variable=self.key_status, color=MUTED, size=9).grid(row=2, column=0, sticky="ew")
        persistence = tk.Frame(form, bg=PANEL)
        persistence.grid(row=3, column=0, sticky="ew", pady=4)
        for mode, caption in (("session", "이번 실행에만 보관"), ("windows", "이 Windows 계정에 암호화 보관")):
            radio = tk.Radiobutton(
                persistence, text=caption, variable=self.key_persistence, value=mode,
                font=_font(self, 9), fg=TEXT, bg=PANEL, activeforeground=TEXT,
                activebackground=PANEL, selectcolor=PANEL_2, highlightcolor=PURPLE,
                anchor="w", takefocus=True,
            )
            radio.pack(anchor="w")
            if mode == "windows" and not self.service.supports_key_persistence:
                radio.configure(state="disabled")
        self.remove_check = self._check(form, self.remove_key, "저장할 때 등록된 키 삭제", command=self._toggle_remove)
        self.remove_check.grid(row=4, column=0, sticky="w", pady=(0, 8))
        ttk.Style(self).configure("Assistant.TCombobox", fieldbackground=PANEL_2, foreground=TEXT)
        self.model_entry = ttk.Combobox(form, textvariable=self.model, values=MODELS, font=_font(self), style="Assistant.TCombobox")
        self.model_entry.bind("<MouseWheel>", self._scroll)
        self._field(form, 5, "2. 사용할 모델", self.model_entry)
        self._wrapped(form, variable=self.price, color=MUTED, size=9).grid(row=7, column=0, sticky="ew", pady=4)
        self.model.trace_add("write", self._update_price)
        self.test_button = _button(form, "연결 시험 · 유료 요청 1회", self._test_connection)
        self.test_button.grid(row=8, column=0, sticky="w", pady=(5, 3))
        self._wrapped(form, "사용 가능 여부는 API 계정마다 달라요. 목록에 없는 모델 ID도 직접 입력할 수 있어요.\n모델 사용 권한과 크레딧 적용 여부는 별개예요. API 계정의 권한·청구 화면에서 확인해 주세요.\n시험은 위의 키·모델로 짧은 요청을 보내며, 입력 중인 설정은 저장하지 않아요.", color=MUTED, size=9).grid(row=9, column=0, sticky="ew")

        self.advanced_button = _button(content, "고급 설정 펼치기 ▾", self._toggle_advanced)
        self.advanced_button.pack(anchor="w", padx=12, pady=(12, 5))
        self.advanced = tk.Frame(content, bg=PANEL)
        self._advanced_open = False
        self._build_advanced()

        usage = tk.Frame(content, bg=PANEL_2, highlightthickness=1, highlightbackground=BORDER)
        usage.pack(fill="x", padx=12, pady=(10, 6))
        self._usage_frame = usage
        usage_header = tk.Frame(usage, bg=PANEL_2)
        usage_header.pack(fill="x", padx=8, pady=5)
        _label(usage_header, "오늘 앱 사용량", size=11).pack(side="left")
        _button(usage_header, "새로고침", self.refresh_usage).pack(side="right")
        self.usage = tk.StringVar(master=self)
        self._wrapped(usage, variable=self.usage).pack(fill="x", padx=8, pady=4)
        self._wrapped(usage, "기록된 비용과 진행 중 요청의 예약 비용을 구분해요. 실제 청구액은 OpenAI 사용량 화면에서 확인해 주세요.", color=MUTED, size=9).pack(fill="x", padx=8, pady=(0, 7))

    def _variable(self, cls=tk.StringVar, **kwargs):
        variable = cls(master=self, **kwargs)
        self._vars.append(variable)
        variable.trace_add("write", self._mark_dirty)
        return variable

    def _wrapped(self, parent, text="", *, variable=None, color=TEXT, size=10):
        options = {"textvariable": variable} if variable is not None else {}
        label = _label(parent, text, color=color, size=size, wraplength=450, **options)
        label.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width)))
        return label

    def _check(self, parent, variable, caption, **kwargs):
        return tk.Checkbutton(
            parent, text=caption, variable=variable, font=_font(self), fg=TEXT, bg=PANEL,
            activeforeground=TEXT, activebackground=PANEL, selectcolor=PANEL_2,
            highlightcolor=PURPLE, anchor="w", takefocus=True, **kwargs,
        )

    @staticmethod
    def _field(form, row, title, widget):
        _label(form, title).grid(row=row, column=0, sticky="w", pady=(7, 3))
        widget.grid(row=row + 1, column=0, sticky="ew", ipady=3)

    def _build_advanced(self):
        content = self.advanced
        self.web_search = self._variable(tk.BooleanVar)
        self.history = self._variable(tk.BooleanVar)
        self.memory = self._variable(tk.BooleanVar)
        self.quiet = self._variable(tk.BooleanVar)
        for variable, caption in (
            (self.web_search, "대화에서 웹 검색 허용 · 검색 비용이 추가될 수 있어요"),
            (self.history, "대화 기록을 이 PC에 저장"),
            (self.memory, "저장한 장기 기억을 다음 대화에 활용"),
        ):
            check = self._check(content, variable, caption)
            check.pack(fill="x", padx=12, pady=2)
            check.bind("<Configure>", lambda event, widget=check: widget.configure(wraplength=max(120, event.width - 32)))
        self._wrapped(content, "기록 저장과 기억 사용은 각각 선택해요. 끄더라도 기존 데이터는 삭제되지 않으며 기억 관리·대화 기록에서 따로 지울 수 있어요.", size=9, color=MUTED).pack(fill="x", padx=12, pady=4)
        _label(content, "먼저 말 걸기 · 간격과 상황", size=11).pack(anchor="w", padx=12, pady=(9, 3))
        self.proactive_interval = self._variable(value="20")
        interval = tk.Spinbox(content, from_=5, to=120, increment=5, textvariable=self.proactive_interval,
                              font=_font(self), fg=TEXT, bg=PANEL_2, insertbackground=TEXT,
                              highlightcolor=PURPLE, width=8)
        interval.bind("<MouseWheel>", self._scroll)
        _label(content, "사용 중 정기 대화 간격 · 5~120분", size=9).pack(anchor="w", padx=12)
        interval.pack(anchor="w", padx=12, pady=(2, 4))
        events = tk.Frame(content, bg=PANEL)
        events.pack(fill="x", padx=20, pady=3)
        self.event_vars = {event: self._variable(tk.BooleanVar) for event in PROACTIVE_EVENTS}
        for index, (event, variable) in enumerate(self.event_vars.items()):
            self._check(events, variable, _EVENT_LABELS[event]).grid(row=index // 2, column=index % 2, sticky="w", padx=(0, 12))
        self._check(content, self.quiet, "오늘은 자동 응원 쉬기 · 저장하면 적용").pack(anchor="w", padx=12, pady=4)
        self._wrapped(content, "먼저 말 걸기도 요청·토큰·비용 한도를 따라요. 상황별 호출은 최소 2분 간격이고, 자리비움·퇴근 모드에는 정기 대화를 쉬어요. 꺼도 기존 타이머 알림과 기본 대사는 계속 나와요.", size=9, color=MUTED).pack(fill="x", padx=12, pady=(0, 6))

        form = tk.Frame(content, bg=PANEL)
        form.pack(fill="x", padx=12)
        form.columnconfigure(0, weight=1)
        self.weather_location = self._variable()
        self.weather_entry = _entry(form, self.weather_location)
        self._field(form, 0, "기본 날씨 지역 · 예: 세종시, 대전시", self.weather_entry)
        self.reading_size = self._variable(value="12")
        reading = tk.Spinbox(form, from_=10, to=20, textvariable=self.reading_size, font=_font(self), fg=TEXT, bg=PANEL_2, insertbackground=TEXT, highlightcolor=PURPLE)
        reading.bind("<MouseWheel>", self._scroll)
        self._field(form, 2, "대화 글자 크기 · 10~20", reading)
        self.request_limit = self._variable()
        self.token_limit = self._variable()
        self.budget = self._variable()
        for row, caption, variable in (
            (4, "하루 요청 한도", self.request_limit),
            (6, "하루 토큰 한도", self.token_limit),
            (8, "하루 추정 비용 한도 (USD)", self.budget),
        ):
            self._field(form, row, caption, _entry(form, variable))
        self._wrapped(form, "빈 칸은 한도 없음이에요. 비용을 추정할 수 없는 모델은 비용 한도 대신 요청·토큰 한도를 사용할 수 있어요.", size=9, color=MUTED).grid(row=10, column=0, sticky="ew", pady=5)

    def _snapshot(self):
        return tuple(variable.get() for variable in self._vars)

    def show(self):
        # External quick settings may change while this window is hidden.
        # Refresh a clean form, but never overwrite an in-progress draft.
        try:
            current = self.service.load_settings()
            if self._base_settings is None or not self.dirty:
                self.reload()
            elif self.dirty and current != self._base_settings:
                self.status.set("다른 화면에서 설정이 바뀌었어요. 입력 중인 초안을 확인한 뒤 저장해 주세요.")
        except Exception:
            self.status.set("최신 설정을 확인하지 못했어요. 입력 중인 초안은 유지했어요.")
        super().show()

    @property
    def dirty(self):
        return self._baseline is not None and self._snapshot() != self._baseline

    def _mark_dirty(self, *_args):
        if self._loading or self._baseline is None:
            return
        dirty = self.dirty
        self.draft_status.set("저장 안 됨 · 닫아도 이번 실행에서 초안을 유지해요." if dirty else "저장된 설정과 같아요.")
        self.discard_button.configure(state="normal" if dirty else "disabled")

    def _toggle_advanced(self):
        self._advanced_open = not self._advanced_open
        if self._advanced_open:
            self.advanced.pack(fill="x", before=self._usage_frame)
        else:
            self.advanced.pack_forget()
        self.advanced_button.configure(text="고급 설정 접기 ▴" if self._advanced_open else "고급 설정 펼치기 ▾")

    def focus_weather(self):
        if not self._advanced_open:
            self._toggle_advanced()
        self.weather_entry.focus_set()
        self.after_idle(lambda: self._ensure_visible(self.weather_entry))

    def _scroll(self, event):
        if not event.delta:
            return
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")
        return "break"

    def _focus_visible(self, event):
        self.after_idle(lambda: self._ensure_visible(event.widget))

    def _ensure_visible(self, widget):
        try:
            if not widget.winfo_exists() or not str(widget).startswith(str(self.content) + "."):
                return
            self.update_idletasks()
            top = widget.winfo_rooty() - self.content.winfo_rooty()
            bottom = top + widget.winfo_height()
            visible_top = self.canvas.canvasy(0)
            visible_bottom = self.canvas.canvasy(self.canvas.winfo_height())
            total = max(1, self.content.winfo_height())
            if top < visible_top:
                self.canvas.yview_moveto(max(0, top - 10) / total)
            elif bottom > visible_bottom:
                self.canvas.yview_moveto(max(0, bottom + 10 - self.canvas.winfo_height()) / total)
        except tk.TclError:
            pass

    def _toggle_remove(self):
        self.key_entry.configure(state="disabled" if self.remove_key.get() else "normal")
        if self.remove_key.get():
            self.key.set("")

    def _update_price(self, *_args):
        model = self.model.get().strip()
        prices = MODEL_PRICES.get(model)
        lines = [MODEL_DESCRIPTIONS.get(model, "직접 입력한 모델 · API 기본 설정으로 요청해요.")]
        effort = MODEL_REASONING_EFFORT.get(model)
        if effort is not None:
            lines[0] += f" · 빠른 응답용 {effort} 추론"
        if prices is None:
            lines.append("이 모델은 앱에서 비용을 추정할 수 없어요. 요청·토큰 한도를 사용할 수 있어요.")
        else:
            lines.append(f"100만 토큰 · 입력 ${prices.input_per_million:g} · 캐시 입력 ${prices.cached_input_per_million:g} · 출력 ${prices.output_per_million:g}")
            if prices.cache_write_multiplier != 1:
                lines.append(f"캐시 쓰기 ${prices.input_per_million * prices.cache_write_multiplier:g} / 100만 토큰 · 기본 30분 보관")
            if prices.long_context_after is not None:
                lines.append(f"입력 {prices.long_context_after:,}토큰 초과 시 입력·캐시 비용 2배, 출력 1.5배")
        self.price.set("\n".join(lines))

    def reload(self):
        try:
            settings = self.service.load_settings()
            has_key = self.service.has_key()
        except Exception:
            self.status.set("AI 설정을 불러오지 못했어요. 다시 열어 주세요.")
            self.save_button.configure(state="disabled")
            return False
        self._loading = True
        try:
            self._base_settings = settings
            self.key.set("")
            self.remove_key.set(False)
            self._toggle_remove()
            self.enabled.set(settings.enabled)
            self.model.set(settings.model)
            self.key_persistence.set(settings.key_persistence)
            self.web_search.set(settings.web_search_enabled)
            self.history.set(settings.conversation_storage_enabled)
            self.memory.set(settings.memory_enabled)
            self.proactive.set(settings.proactive_enabled)
            self.proactive_interval.set(str(settings.proactive_interval_minutes))
            self.quiet.set(settings.proactive_quiet_until == date.today().isoformat())
            for event, variable in self.event_vars.items():
                variable.set(event in settings.proactive_events)
            self.weather_location.set(settings.weather_location)
            self.reading_size.set(str(settings.reading_text_size))
            for variable, value in ((self.request_limit, settings.daily_request_limit), (self.token_limit, settings.daily_token_limit), (self.budget, settings.daily_budget_usd)):
                variable.set("" if value is None else str(value))
            storage = "Windows 암호화 보관" if self.service.persistent_key else "이번 실행에만 보관"
            self.key_status.set(f"키 등록됨 · {storage}" if has_key else "키 미등록 · 입력 후 설정을 저장해 주세요.")
            self.remove_check.configure(state="normal" if has_key else "disabled")
            self.save_button.configure(state="normal")
            self.status.set(self.service.settings_issue)
            self._baseline = self._snapshot()
        finally:
            self._loading = False
        self._mark_dirty()
        return True

    def refresh_usage(self):
        try:
            settings = self.service.load_settings()
            usage = self.service.ledger.summary(settings)
            text = _usage_text(self.service)
            text += f"\n요청 {usage.requests:,}회 · 토큰 {usage.total_tokens:,}개"
            unconfirmed = getattr(usage, "unconfirmed_requests", 0)
            if unconfirmed:
                text += f" · 사용량 미확인 {unconfirmed:,}회"
            self.usage.set(text)
        except Exception:
            self.usage.set("사용량을 불러오지 못했어요. 다시 새로고침해 주세요.")

    def _candidate(self):
        try:
            request = self.request_limit.get().strip()
            tokens = self.token_limit.get().strip()
            budget = self.budget.get().strip()
            settings = replace(
                self._base_settings, enabled=self.enabled.get(), model=self.model.get().strip(),
                key_persistence=self.key_persistence.get(), web_search_enabled=self.web_search.get(),
                conversation_storage_enabled=self.history.get(), memory_enabled=self.memory.get(),
                proactive_enabled=self.proactive.get(),
                proactive_interval_minutes=int(self.proactive_interval.get()),
                proactive_events=tuple(event for event, variable in self.event_vars.items() if variable.get()),
                proactive_quiet_until=date.today().isoformat() if self.quiet.get() else "",
                reading_text_size=int(self.reading_size.get()), weather_location=self.weather_location.get().strip(),
                daily_request_limit=int(request) if request else None,
                daily_token_limit=int(tokens) if tokens else None,
                daily_budget_usd=float(budget) if budget else None,
            )
        except (ValueError, tk.TclError):
            raise SettingsError("말 걸기 간격·글자 크기·요청·토큰 한도는 정수로, 비용 한도는 숫자로 입력해 주세요.") from None
        settings.validate()
        return settings

    def _save(self):
        if self._base_settings is None:
            return False
        try:
            candidate = self._candidate()
            self.service.save_settings(candidate, new_key=self.key.get().strip() or None, remove_key=self.remove_key.get())
        except (SettingsError, ValueError) as error:
            self.status.set(str(error))
            return False
        except Exception:
            self.status.set("AI 설정을 저장하지 못했어요. 초안은 유지했어요.")
            return False
        self.reload()
        self.status.set("AI 설정을 저장했어요.")
        self.refresh_usage()
        self.owner.settings_changed()
        return True

    def _test_connection(self):
        if self._test_cancel is not None:
            return
        if self.remove_key.get():
            self.status.set("키 삭제 선택을 해제한 뒤 연결을 시험해 주세요.")
            return
        key, model = self.key.get().strip() or None, self.model.get().strip()
        cancel = Event()
        self._test_cancel = cancel
        self.test_button.configure(state="disabled")
        self.status.set("선택한 키·모델로 연결을 시험하고 있어요… · 유료 요청 1회")

        def done(value, error):
            self._test_cancel = None
            self.test_button.configure(state="normal")
            self.status.set(str(error) if error is not None else str(value))
            self.refresh_usage()

        self.owner.run_background(lambda: self.service.connection_test(new_key=key, model=model, cancel=cancel), done)
