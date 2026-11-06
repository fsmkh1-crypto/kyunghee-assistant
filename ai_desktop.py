"""Optional AI UI adapter; timer/state and local dialogue stay authoritative."""
from __future__ import annotations

from collections import deque
import ctypes
from ctypes import wintypes
from dataclasses import dataclass, replace
from datetime import datetime
import hashlib
import os
from pathlib import Path
import re
import tempfile
import time
import tkinter as tk
from tkinter import filedialog

from PIL import Image

import app as core
import asset_manager
from ai_credentials import AICredentials
from ai_dialogue import AIService, HTTPClient, error_message
from ai_settings_ui import AISettingsPanel
from asset_pack_import import import_numbered_pack
from chat_asset_commands import (
    MAX_CATALOG_IMAGES, AssetCatalog, AssetChoice, guard_asset_command,
    is_asset_change_request, is_timer_status_query,
)
from font_support import ui_font
from messages import pick


CHAT_REPLY_TIMEOUT_SECONDS = 5.0


def chat_window_rect(root_rect, work_area, size=(410, 500), gap=8):
    """Prefer an adjacent window, including a monitor with negative coordinates."""
    root_x, root_y, root_width, _root_height = root_rect
    left, top, right, bottom = work_area
    width, height = min(size[0], right - left), min(size[1], bottom - top)
    right_x, left_x = root_x + root_width + gap, root_x - width - gap
    if left <= right_x and right_x + width <= right:
        x = right_x
    elif left <= left_x and left_x + width <= right:
        x = left_x
    else:
        candidates = (min(max(right_x, left), right - width),
                      min(max(left_x, left), right - width))
        x = min(candidates, key=lambda value: max(0, min(value + width, root_x + root_width)
                                                  - max(value, root_x)))
    y = min(max(root_y, top), bottom - height)
    return int(x), int(y), int(width), int(height)


def place_chat_window(window, x, y, width, height):
    """Use absolute Windows coordinates for monitors left of or above primary."""
    window.geometry(f"{width}x{height}{x:+d}{y:+d}")
    window.update_idletasks()
    if os.name == "nt":
        try:
            user32 = ctypes.windll.user32
            user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
            user32.GetAncestor.restype = wintypes.HWND
            client = int(window.winfo_id())
            wrapper = user32.GetAncestor(client, 2) or client  # GA_ROOT
            user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                            ctypes.c_int, ctypes.c_int, wintypes.UINT]
            user32.SetWindowPos.restype = wintypes.BOOL
            user32.SetWindowPos(wrapper, 0, x, y, width, height, 0x0014)  # no z-order/activation change
        except Exception:
            core.log.warning("chat window placement unavailable")


@dataclass(frozen=True)
class PendingChat:
    event: str
    user_text: str
    token: tuple
    deadline: float
    asset_catalog: AssetCatalog | None = None


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
        self.root.after_idle(lambda: self._open_chat() if not self._ai_closed else None)

    def _build_timer_page(self):
        super()._build_timer_page()
        self.speech.bind("<Button-1>", self._open_chat)

    def _stop_character_drag(self, event):
        dragged = self._character_dragged
        self._stop_drag(event)
        self._character_dragged = False
        if not dragged:
            self._open_chat()

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
        selection = [self.preferences.builtin_image_set, self.character_role,
                     tuple(sorted(self._manual_asset_overrides.items()))]
        for key, _caption in self.IMAGE_ROWS:
            selection.extend((getattr(self.preferences, f"image_{key}", ""),
                              getattr(self.preferences, f"image_{key}_mode", "fit")))
        for name in ("image_path_vars", "image_mode_vars", "image_alignment_vars"):
            selection.append(tuple((key, variable.get()) for key, variable in sorted(getattr(self, name, {}).items())))
        selection.append(getattr(self, "builtin_image_set_var", None).get()
                         if hasattr(self, "builtin_image_set_var") else "")
        try:
            info = self._image_set_store.manifest_path.stat()
            selection.append((info.st_mtime_ns, info.st_size))
        except OSError:
            selection.append(None)
        asset_signature = hashlib.sha256(repr(selection).encode("utf-8")).hexdigest()
        return (self._ai_revision, self.state.daily.day, self.state.session.is_away,
                self._current_workday_state().mode, self.preferences.personality, asset_signature)

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

    def _request_ai(self, event, user_text="", *, asset_catalog=None):
        if not self._ai_ready or self._ai_closed:
            return False
        options = {"asset_catalog": asset_catalog} if asset_catalog is not None else {}
        return self.ai_service.request(event, self._ai_context(), user_text=user_text,
                                       token=self._ai_token(), **options)

    def _chat_asset_catalog(self):
        """Send pathless capabilities; retain all filesystem references locally."""
        choices, paths = [], {}
        roles = dict(self.IMAGE_ROWS)
        for role, _label, path in self._catalog():
            if role not in roles:
                continue
            ref = self._encode_asset_ref(path)
            if not ref.startswith(("builtin:", "user:", "userset:")):
                continue
            asset_id = "img_" + hashlib.sha256(ref.encode("utf-8")).hexdigest()[:24]
            builtin = ref.startswith("builtin:")
            match = re.fullmatch(r"[a-z]+_(\d{2})\.png", path.name, re.I) if builtin else None
            try:
                choice = AssetChoice(asset_id, role, int(match.group(1)) if match else None,
                                     path.name if builtin else "")
            except ValueError:
                continue
            choices.append(choice)
            paths[asset_id] = path
            if len(choices) >= MAX_CATALOG_IMAGES:
                break
        current = self._manual_asset_overrides.get(self.ROLE_TO_SETTING.get(self.character_role, "default"), "")
        current_id = "img_" + hashlib.sha256(current.encode("utf-8")).hexdigest()[:24] if current else None
        if current_id not in paths:
            current_id = None
        number = self.preferences.builtin_image_set
        catalog = AssetCatalog(tuple(asset_manager.available_complete_sets(asset_manager.ASSET_DIR)), tuple(choices),
                               int(number) if str(number).isdigit() else None, current_id)
        return catalog, paths

    @staticmethod
    def _is_timer_question(text):
        return is_timer_status_query(text)

    def _timer_chat_reply(self):
        return (f"지금은 {datetime.now():%H:%M:%S}이고 오늘 실제 사용은 {core.fmt(self.state.daily.active_seconds)}, "
                f"자리비움은 {core.fmt(self.state.daily.away_seconds)}이야. "
                f"지금 연속 사용은 {core.fmt(self.state.session.continuous_seconds)}이고 "
                + ("자리비움 중이야." if self.state.session.is_away else "사용 중이야."))

    def _apply_chat_tool_result(self, result, pending):
        calls = getattr(result, "tool_calls", ())
        update_speech = True
        try:
            if len(calls) != 1 or pending.asset_catalog is None:
                raise ValueError
            catalog, paths = self._chat_asset_catalog()
            command = guard_asset_command(calls[0].command, pending.user_text, catalog)
            if pending.token != self._ai_token() or time.monotonic() >= pending.deadline:
                self._cancel_pending_chat()
                return
            if command.kind == "set":
                _ok, message = self._select_chat_asset(number=command.number)
            elif command.kind == "file":
                _ok, message = self._select_chat_asset(path=paths.get(command.asset_id))
            elif command.kind == "list":
                numbers = ", ".join(f"{value:02d}" for value in catalog.sets) or "없음"
                message = f"설치된 전체 세트는 {numbers}이야. '03번 세트로 바꿔줘'처럼 요청하면 지금 화면의 이미지와 전체 기본 세트를 바꿀 수 있어. 다른 수동 이미지는 유지해."
            elif command.kind == "status":
                message, update_speech = self._timer_chat_reply(), False
            else:
                raise ValueError
        except Exception:
            message = "요청할 이미지나 동작을 정확히 확인하지 못했어. 세트 번호나 갤러리 파일을 하나만 지정해 줘. 설정은 바꾸지 않았어."
        self.ai_service.record_tool_result(result, message)
        self._chat_pending = None
        self._ai_invalidate()
        self._finish_chat_reply(message, "타이머" if not update_speech else "설정", "앱에서 요청 결과를 확인했어요.",
                                update_speech=update_speech)

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
        return self._open_chat(event)

    @staticmethod
    def _restore_chat_selection_file(path, content):
        """Restore only our two known selection files after a partial save."""
        current = path.read_bytes() if path.is_file() else None
        if current == content:
            return
        if content is None:
            path.unlink(missing_ok=True)
            return
        fd, name = tempfile.mkstemp(prefix=f".{path.name}.restore-", dir=path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(fd, "wb") as output:
                output.write(content)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)

    def _select_chat_asset(self, *, number=None, path=None):
        """Apply a verified selection to the visible role; never delete artwork.

        A whole-set command also changes the global built-in selector. Other
        manually selected slots and imported image lists remain untouched.
        """
        role = self.character_role or "default"
        key = self.ROLE_TO_SETTING.get(role, "default")
        if number is not None:
            complete = asset_manager.available_complete_sets(asset_manager.ASSET_DIR)
            if type(number) is not int or number not in complete:
                return False, "그 번호의 완성 세트가 설치되어 있지 않아. 설치된 세트 목록을 확인해 줘."
            canonical_role = self.SETTING_TO_CANONICAL_ROLE.get(key, "default")
            path = asset_manager.variant_asset(canonical_role, number, asset_manager.ASSET_DIR)
        if path is None:
            return False, "선택할 이미지를 찾지 못했어. 설치된 이미지에서 다시 골라 줘."
        path = Path(path)
        try:
            catalog = {entry[2].resolve() for entry in self._catalog()}
            if path.resolve() not in catalog:
                raise ValueError
            ref = self._encode_asset_ref(path)
            if not ref.startswith(("builtin:", "user:", "userset:")):
                raise ValueError
            self._validate_image_source(path)
            with Image.open(path) as image:
                image.convert("RGBA").load()
        except Exception:
            return False, "그 이미지를 안전하게 열 수 없어 변경하지 않았어. 갤러리에서 다른 이미지를 골라 줘."

        previous_preferences = self.preferences
        previous_overrides = dict(self._manual_asset_overrides)
        previous_gallery = dict(self._gallery_previous)
        previous_photo = self.character_photo
        previous_bbox = getattr(self, "_character_alpha_bbox", None)
        selection_paths = (Path(self.MANUAL_OVERRIDE_FILE), Path(core.SETTINGS_FILE))
        try:
            previous_files = {item: item.read_bytes() if item.is_file() else None for item in selection_paths}
            variables = [self.builtin_image_set_var, self.image_name_vars[key], self.image_builtin_vars[key]]
            previous_variables = [(variable, variable.get()) for variable in variables]
        except Exception:
            return False, "기존 설정을 확인할 수 없어 이미지 변경을 시작하지 않았어."
        try:
            self._gallery_previous[key] = previous_overrides.get(key, self.FOLLOW_SENTINEL)
            self._manual_asset_overrides[key] = ref
            self._save_manual_overrides()
            candidate = replace(previous_preferences, builtin_image_set=f"{number:02d}") if number is not None else previous_preferences
            self.apply_preferences(candidate)
            self.builtin_image_set_var.set(self._builtin_base_label(self.preferences.builtin_image_set))
            self.image_name_vars[key].set(path.name)
            self.image_builtin_vars[key].set("세트 기본값")
            self._image_cache.clear()
            self._invalidate_settings_preview(key)
            self._settings_preview_indices[key] = 0
            self._select_settings_preview(key)
            self.character_role = None
            self._set_character(role)
            if self.character_role != role or self.character_photo is previous_photo:
                raise RuntimeError("render_failed")
            self._apply_widget_appearance()
            if self.current_page == "timer":
                self._resize_for_page("timer")
        except Exception:
            self.preferences = previous_preferences
            self._manual_asset_overrides = previous_overrides
            self._gallery_previous = previous_gallery
            restored = True
            for item, content in previous_files.items():
                try:
                    self._restore_chat_selection_file(item, content)
                except Exception:
                    restored = False
            for variable, value in previous_variables:
                variable.set(value)
            self._image_cache.clear()
            self.character_photo = previous_photo
            self.character.configure(image=previous_photo)
            self.character_role = role
            self._character_alpha_bbox = previous_bbox
            self._apply_widget_appearance()
            if restored:
                return False, "이미지 변경을 저장하거나 표시하지 못해 취소했어. 기존 설정과 이미지를 유지했어."
            return False, "이미지 변경을 완료하지 못했어. 설정의 저장 상태를 확인해 줘."
        caption = dict(self.IMAGE_ROWS).get(key, key)
        if number is not None:
            return True, f"전체 기본 세트를 {number:02d}번으로 바꾸고 지금 화면의 {caption} 이미지를 선택했어. 다른 수동 이미지와 원본 파일은 그대로 뒀어."
        # This acknowledgement can enter bounded API chat memory. Custom file
        # names remain local just like the opaque catalog's custom metadata.
        selected = path.name if ref.startswith("builtin:") else "선택한 이미지"
        return True, f"지금 화면의 {caption} 이미지를 {selected}로 바꿨어. 다른 상황의 이미지와 원본 파일은 그대로 뒀어."

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
                elif getattr(result, "tool_calls", ()):
                    self._apply_chat_tool_result(result, pending)
                elif self._is_timer_question(pending.user_text):
                    self._finish_chat_reply(self._timer_chat_reply(), "타이머", "현재 타이머 기록이에요.", update_speech=False)
                elif is_asset_change_request(pending.user_text):
                    self._finish_chat_reply("이미지 변경 도구가 호출되지 않아 설정은 그대로야. 설치된 세트 번호나 파일 이름을 하나만 지정해 줘.",
                                            "설정", "실제 이미지 변경은 적용하지 않았어요.")
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
        root_rect = (self.root.winfo_x(), self.root.winfo_y(), self.root.winfo_width(), self.root.winfo_height())
        area = self._best_work_area(*root_rect)
        x, y, width, height = chat_window_rect(root_rect, area)
        win.minsize(min(340, width), min(360, height))
        place_chat_window(win, x, y, width, height)
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
        catalog = self._chat_asset_catalog()[0] if enabled and event == "chat" else None
        if enabled and not self._request_ai(event, user_text=text if event == "chat" else "", asset_catalog=catalog):
            self._chat_ai_note = "지금은 AI 요청을 시작할 수 없어요. 잠시 후 다시 보내 주세요."
            self._refresh_chat()
            return False
        self._chat_messages.extend((("나", text), ("승아 · 대기 중", "답변을 생각하고 있어요…")))
        self._chat_pending = PendingChat(event, text, self._ai_token(),
                                         time.monotonic() + CHAT_REPLY_TIMEOUT_SECONDS, catalog)
        # Prevent periodic idle dialogue from replacing the existing speech
        # while this explicit chat is waiting. Timer and meaningful events run on.
        self.last_dialogue_at = time.monotonic()
        if enabled:
            self._chat_ai_note = "AI 답변을 기다리고 있어요."
        elif event == "chat" and self._is_timer_question(text):
            self._finish_chat_reply(self._timer_chat_reply(), "타이머", "현재 타이머 기록이에요.", update_speech=False)
        elif event == "chat" and is_asset_change_request(text):
            self._finish_chat_reply("이미지를 바꾸려면 AI 설정에서 API를 켜 줘. 지금은 설정을 바꾸지 않았어.",
                                    "설정", "AI 연결이 꺼져 있어 이미지 선택을 유지했어요.")
        else:
            self._fallback_pending_chat()
        self._refresh_chat()
        return True

    def _finish_chat_reply(self, text, source, note, *, update_speech=True):
        self._chat_pending = None
        if self._chat_messages and self._chat_messages[-1][0] == "승아 · 대기 중":
            self._chat_messages[-1] = (f"승아 · {source}", text)
        # Explicit chat still completes in its window during fullscreen mode;
        # the timer overlay continues to respect presentation suppression.
        if update_speech and not self._break_notifications_suppressed():
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
        if pending.event == "chat" and self._is_timer_question(pending.user_text):
            self._finish_chat_reply(self._timer_chat_reply(), "타이머", "연결 대신 현재 타이머 기록을 확인했어요.", update_speech=False)
            return
        if pending.event == "chat" and is_asset_change_request(pending.user_text):
            self._finish_chat_reply("이미지 변경 요청을 완료하지 못했어. 설정은 그대로 두었으니 잠시 후 다시 요청해 줘.",
                                    "설정", error_message(error_code) if error_code else "이미지 선택을 유지했어요.")
            return
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
            "AI 사용 중 · 필요한 타이머 정보와 보낸 대화가 OpenAI로 전송됩니다. 이미지 변경과 사용 시간 확인을 요청할 수 있어요."
            if enabled else "로컬 대화 중 · '사용 시간 알려줘'로 현재 기록을 확인할 수 있어요. AI 설정에서 API를 켜면 더 자연스럽게 답해요.")
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
