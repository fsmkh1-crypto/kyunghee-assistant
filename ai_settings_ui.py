"""Embeddable Tk settings for optional OpenAI use.

All widget access belongs to the Tk thread. Connection tests run in one daemon
worker and return a sanitized result through a queue polled by ``after``.
The caller owns normal preferences and configures the AI service in on_apply.
"""
from __future__ import annotations

import queue
import threading
import tkinter as tk
from typing import Callable, Mapping

from ai_credentials import AICredentials, normalize_api_key
from settings import UserSettings


_DEFAULT_THEME = {
    "bg": "#0E1528", "input": "#121B31", "text": "#F5F7FF",
    "muted": "#9AA5BD", "accent": "#7C4DFF", "good": "#4ADE80",
    "warning": "#F59E0B",
}

_TEST_ERRORS = {
    "invalid_key": "키가 올바르지 않습니다. API 키를 확인해 주세요.",
    "permission_denied": "이 API 프로젝트에서 모델 사용 권한을 확인해 주세요.",
    "rate_limited": "API 사용 한도 또는 결제 상태를 확인해 주세요.",
    "timeout": "연결 시간이 초과되었습니다. 잠시 후 다시 확인해 주세요.",
    "connection_error": "OpenAI에 연결하지 못했습니다. 네트워크를 확인해 주세요.",
    "service_error": "OpenAI 서비스에 일시적인 문제가 있습니다.",
    "invalid_response": "응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.",
    "request_error": "연결 테스트를 완료하지 못했습니다. API 설정을 확인해 주세요.",
}

DATA_NOTICE = (
    "AI를 ON으로 적용하면 대사·알림 이벤트와 전송한 대화에 OpenAI API를 사용합니다. "
    "이벤트 시각, 실제 사용·연속 사용 시간, 최근 자리비움·휴식, 오늘 주요 이벤트, "
    "말투 프리셋과 최근 대사·대화가 함께 전송됩니다. 에셋 선택·목록 요청에는 선택 가능한 에셋 번호와 "
    "이미지 역할·이름·식별자도 포함됩니다. 이미지 파일 자체와 전체 파일 경로는 전송하지 않습니다. "
    "연결 테스트도 API 요청을 보냅니다."
)
KEY_NOTICE = (
    "API 키는 OpenAI에 TLS(HTTPS) 인증용으로만 전송합니다. "
    "본인 OpenAI API 계정·프로젝트의 키가 필요하며, API 요금은 ChatGPT 구독과 별도로 발생합니다. "
    "기본값은 이번 실행 중에만 사용입니다."
)


class AISettingsPanel(tk.Frame):
    """Create and pack this panel into the existing settings content frame.

    on_apply(enabled, remember, api_key) must persist only the two booleans and
    configure the runtime service. It runs synchronously on the Tk thread.
    test_connection(api_key) is injected (normally HTTPClient.test_connection)
    and must return an object with safe ``ok`` and ``error_code`` attributes.
    The entry is never filled with a loaded or previously submitted key.
    """

    def __init__(
        self,
        parent,
        settings: UserSettings,
        credentials: AICredentials,
        *,
        on_apply: Callable[[bool, bool, str], None],
        test_connection: Callable[[str], object],
        font_family: str = "Pretendard",
        theme: Mapping[str, str] | None = None,
    ):
        self.theme = {**_DEFAULT_THEME, **(theme or {})}
        super().__init__(parent, bg=self.theme["bg"], highlightthickness=0)
        self.credentials = credentials
        self._on_apply = on_apply
        self._test_connection = test_connection
        self._font_family = font_family
        self._closed = False
        self._testing = False
        self._generation = 0
        self._poll_job = None
        self._test_results: queue.Queue[tuple[int, bool, str]] = queue.Queue(maxsize=1)
        self.enabled_var = tk.BooleanVar(master=self, value=settings.ai_enabled)
        self.remember_var = tk.BooleanVar(
            master=self, value=settings.ai_remember_key and credentials.supports_persistence
        )
        self.key_var = tk.StringVar(master=self, value="")
        self.status_var = tk.StringVar(master=self, value=self._key_status())

        self._label("AI 설정", size=11).pack(anchor="w", pady=(9, 5))
        row = tk.Frame(self, bg=self.theme["bg"])
        row.pack(fill="x", pady=(0, 4))
        self._label("AI 대사 · 대화", parent=row).pack(side="left", padx=(0, 12))
        for caption, value in (("OFF", False), ("ON", True)):
            tk.Radiobutton(
                row, text=caption, value=value, variable=self.enabled_var,
                command=self._toggle_enabled, **self._check_style(),
            ).pack(side="left", padx=(0, 7))

        self._label("OpenAI API 키", size=9).pack(anchor="w", pady=(4, 3))
        self.key_entry = tk.Entry(
            self, textvariable=self.key_var, show="●", relief="flat", bd=0,
            font=(font_family, 10), fg=self.theme["text"], bg=self.theme["input"],
            insertbackground=self.theme["text"], exportselection=False,
        )
        self.key_entry.pack(fill="x", ipady=6)
        self._label("비워 두면 현재 실행의 키를 유지합니다.", size=8, muted=True).pack(anchor="w", pady=(3, 5))
        self.remember_check = tk.Checkbutton(
            self, text="키 기억 (이 Windows 계정만 · DPAPI 암호화)",
            variable=self.remember_var, command=self._remember_toggled,
            **self._check_style(),
        )
        self.remember_check.pack(anchor="w")
        if not credentials.supports_persistence:
            self.remember_check.configure(state="disabled")
            self._label("이 환경에서는 키를 실행 중에만 사용할 수 있습니다.", size=8, muted=True).pack(anchor="w", pady=(2, 4))

        self._notices = []
        for text in (KEY_NOTICE, DATA_NOTICE):
            label = self._label(text, size=8, muted=True, wraplength=420)
            label.pack(fill="x", anchor="w", pady=(6, 0))
            self._notices.append(label)

        buttons = tk.Frame(self, bg=self.theme["bg"])
        buttons.pack(fill="x", pady=(10, 5))
        self.apply_button = self._button(buttons, "AI 설정 적용", self.apply, primary=True)
        self.apply_button.pack(side="left", padx=(0, 7))
        self.test_button = self._button(buttons, "연결 테스트", self.test_connection)
        self.test_button.pack(side="left", padx=(0, 7))
        self.clear_button = self._button(buttons, "키 지우기", self.clear_key)
        self.clear_button.pack(side="left")
        self.status_label = tk.Label(
            self, textvariable=self.status_var, font=(font_family, 8),
            bg=self.theme["bg"], fg=self.theme["muted"], anchor="w",
            justify="left", wraplength=420,
        )
        self.status_label.pack(fill="x", anchor="w", pady=(2, 7))
        self.bind("<Configure>", self._resize_notices)
        self.bind("<Destroy>", self._destroyed, add="+")
        self._sync_test_button()

    def _label(self, text, *, parent=None, size=9, muted=False, **kwargs):
        return tk.Label(
            parent or self, text=text, font=(self._font_family, size),
            bg=self.theme["bg"], fg=self.theme["muted" if muted else "text"],
            anchor="w", justify="left", **kwargs,
        )

    def _check_style(self):
        return dict(
            font=(self._font_family, 9), fg=self.theme["text"], bg=self.theme["bg"],
            activeforeground=self.theme["text"], activebackground=self.theme["bg"],
            selectcolor=self.theme["input"], highlightthickness=0, bd=0, cursor="hand2",
        )

    def _button(self, parent, caption, command, *, primary=False):
        return tk.Button(
            parent, text=caption, command=command, font=(self._font_family, 9),
            bg=self.theme["accent" if primary else "input"], fg=self.theme["text"],
            activebackground=self.theme["accent"], activeforeground=self.theme["text"],
            relief="flat", bd=0, padx=8, pady=5, cursor="hand2",
        )

    def _key_status(self):
        return "현재 실행에서 사용할 키가 준비되어 있습니다." if self.credentials.has_key else "키를 입력하면 AI를 사용할 수 있습니다."

    def _status(self, message: str, *, ok=True):
        self.status_var.set(message)
        self.status_label.configure(fg=self.theme["good" if ok else "warning"])

    def _resize_notices(self, event):
        width = max(170, event.width)
        for label in self._notices:
            label.configure(wraplength=width)
        self.status_label.configure(wraplength=width)

    def _sync_test_button(self):
        available = self.enabled_var.get() and not self._testing
        self.test_button.configure(state="normal" if available else "disabled")

    def _toggle_enabled(self):
        self._generation += 1
        self._sync_test_button()
        self._status("AI 설정 적용을 누르면 ON/OFF가 반영됩니다.")

    def _remember_toggled(self):
        if not self.remember_var.get():
            status = self.credentials.delete_saved_key()
            self._status(status.message, ok=status.ok)

    def refresh(self, settings: UserSettings):
        """Synchronize externally changed booleans without revealing the key."""
        self.enabled_var.set(settings.ai_enabled)
        self.remember_var.set(settings.ai_remember_key and self.credentials.supports_persistence)
        self.key_var.set("")
        self._generation += 1
        self._sync_test_button()

    def apply(self):
        self._generation += 1
        status = self.credentials.configure_key(self.key_var.get(), self.remember_var.get())
        if status.code == "invalid_key_format":
            self._status(status.message, ok=False)
            return
        self.key_var.set("")
        self.remember_var.set(status.remembered)
        try:
            self._on_apply(self.enabled_var.get(), status.remembered, self.credentials.api_key)
        except Exception:
            self._status("설정을 저장하지 못했습니다. 폴더 권한을 확인해 주세요.", ok=False)
            return
        prefix = "AI ON · " if self.enabled_var.get() else "AI OFF · "
        self._status(prefix + status.message, ok=status.ok)

    def clear_key(self):
        self._generation += 1
        status = self.credentials.clear()
        self.key_var.set("")
        self.remember_var.set(False)
        try:
            self._on_apply(self.enabled_var.get(), False, "")
        except Exception:
            self._status("실행 중인 키는 지웠습니다. 설정 저장은 실패했습니다.", ok=False)
            return
        self._status(status.message, ok=status.ok)

    def test_connection(self):
        if self._testing or not self.enabled_var.get():
            return
        try:
            api_key = normalize_api_key(self.key_var.get()) or self.credentials.api_key
        except ValueError:
            self._status("API 키에는 공백·줄바꿈 없이 키 문자열만 입력해 주세요.", ok=False)
            return
        if not api_key:
            self._status("연결을 확인할 API 키를 입력해 주세요.", ok=False)
            return
        self._testing = True
        self._sync_test_button()
        self._status("OpenAI 연결 확인 중… (API 요금이 발생할 수 있습니다.)")
        generation = self._generation

        def worker():
            try:
                result = self._test_connection(api_key)
                ok = getattr(result, "ok", False) is True
                code = getattr(result, "error_code", "request_error")
                code = code if isinstance(code, str) and code in _TEST_ERRORS else "request_error"
            except Exception:
                ok, code = False, "connection_error"
            # No Tk calls, after calls, logging, or raw exceptions in this thread.
            self._test_results.put_nowait((generation, ok, code))

        threading.Thread(target=worker, name="ai-settings-connection", daemon=True).start()
        self._poll_job = self.after(80, self._poll_test_result)

    def _poll_test_result(self):
        self._poll_job = None
        if self._closed:
            return
        try:
            generation, ok, code = self._test_results.get_nowait()
        except queue.Empty:
            self._poll_job = self.after(80, self._poll_test_result)
            return
        self._testing = False
        self._sync_test_button()
        if generation != self._generation:
            return
        self._status("OpenAI 연결을 확인했습니다." if ok else _TEST_ERRORS[code], ok=ok)

    def _destroyed(self, event):
        if event.widget is not self:
            return
        self._closed = True
        self._generation += 1
        self.key_var.set("")
        if self._poll_job is not None:
            self.after_cancel(self._poll_job)
            self._poll_job = None
