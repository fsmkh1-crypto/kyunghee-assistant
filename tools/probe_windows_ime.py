"""Real Korean IME / ChatWindow probe; sends fixed text only to an in-memory sink.

Exit 0: actual composition observed and current UI preserved it in every case.
Exit 1: a probe error, or current UI lost/duplicated text after real composition.
Exit 3: Windows, foreground ownership, Korean layout, or composition unavailable.

No Text.insert, event_generate, Unicode packet, or direct widget invocation is
used to produce a test input or submit it. Keyboard/mouse input uses SendInput.
The optional baseline files are loaded into separate Python modules, not copied
over the checkout. Baseline failures are evidence, never a current-build failure.
"""
from __future__ import annotations

import argparse
import ctypes as C
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import logging
import os
from pathlib import Path
import platform
import socket
import sys
import tempfile
import time
import traceback
from types import SimpleNamespace
import uuid


U32, U16, LONG, HANDLE = C.c_uint32, C.c_uint16, C.c_int32, C.c_void_p


class GUID(C.Structure):
    _fields_ = [("Data1", U32), ("Data2", U16), ("Data3", U16), ("Data4", C.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)

    def text(self):
        return str(uuid.UUID(bytes_le=bytes(self)))


class Profile(C.Structure):
    _fields_ = [("type", U32), ("langid", U16), ("clsid", GUID), ("profile", GUID),
                ("category", GUID), ("substitute", HANDLE), ("caps", U32),
                ("hkl", HANDLE), ("flags", U32)]


class KeyInput(C.Structure):
    _fields_ = [("vk", U16), ("scan", U16), ("flags", U32), ("time", U32), ("extra", C.c_size_t)]


class MouseInput(C.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("data", U32), ("flags", U32),
                ("time", U32), ("extra", C.c_size_t)]


class HardwareInput(C.Structure):
    _fields_ = [("message", U32), ("low", U16), ("high", U16)]


class InputUnion(C.Union):
    _fields_ = [("ki", KeyInput), ("mi", MouseInput), ("hi", HardwareInput)]


class Input(C.Structure):
    _anonymous_ = ("value",)
    _fields_ = [("type", U32), ("value", InputUnion)]


class Unavailable(RuntimeError):
    pass


class WinAPI:
    def __init__(self):
        self.input_guard = None
        self.input_delivery_errors = []
        self.user = C.WinDLL("user32", use_last_error=True)
        self.imm = C.WinDLL("imm32", use_last_error=True)
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.ole = C.WinDLL("ole32", use_last_error=True)
        declarations = (
            (self.user, "GetFocus", HANDLE, ()),
            (self.user, "GetForegroundWindow", HANDLE, ()),
            (self.user, "GetAncestor", HANDLE, (HANDLE, U32)),
            (self.user, "GetWindowThreadProcessId", U32, (HANDLE, C.POINTER(U32))),
            (self.user, "SetForegroundWindow", LONG, (HANDLE,)),
            (self.user, "GetKeyboardLayout", HANDLE, (U32,)),
            (self.user, "GetKeyboardLayoutList", C.c_int, (C.c_int, C.POINTER(HANDLE))),
            (self.user, "ActivateKeyboardLayout", HANDLE, (HANDLE, U32)),
            (self.user, "LoadKeyboardLayoutW", HANDLE, (C.c_wchar_p, U32)),
            (self.user, "UnloadKeyboardLayout", LONG, (HANDLE,)),
            (self.user, "GetKeyState", C.c_short, (C.c_int,)),
            (self.user, "GetAsyncKeyState", C.c_short, (C.c_int,)),
            (self.user, "SendInput", U32, (U32, C.POINTER(Input), C.c_int)),
            (self.user, "SetCursorPos", LONG, (C.c_int, C.c_int)),
            (self.kernel, "GetCurrentThreadId", U32, ()),
            (self.kernel, "ProcessIdToSessionId", LONG, (U32, C.POINTER(U32))),
            (self.imm, "ImmGetContext", HANDLE, (HANDLE,)),
            (self.imm, "ImmReleaseContext", LONG, (HANDLE, HANDLE)),
            (self.imm, "ImmGetCompositionStringW", LONG, (HANDLE, U32, HANDLE, U32)),
            (self.imm, "ImmGetConversionStatus", LONG, (HANDLE, C.POINTER(U32), C.POINTER(U32))),
            (self.imm, "ImmGetOpenStatus", LONG, (HANDLE,)),
            (self.imm, "ImmSetOpenStatus", LONG, (HANDLE, LONG)),
            (self.imm, "ImmSetConversionStatus", LONG, (HANDLE, U32, U32)),
            (self.imm, "ImmNotifyIME", LONG, (HANDLE, U32, U32, U32)),
            (self.imm, "ImmGetDescriptionW", U32, (HANDLE, C.c_wchar_p, U32)),
            (self.ole, "CoInitializeEx", LONG, (HANDLE, U32)),
            (self.ole, "CoUninitialize", None, ()),
            (self.ole, "CoCreateInstance", LONG,
             (C.POINTER(GUID), HANDLE, U32, C.POINTER(GUID), C.POINTER(HANDLE))),
        )
        for dll, name, restype, argtypes in declarations:
            fn = getattr(dll, name)
            fn.restype, fn.argtypes = restype, argtypes

    def process(self, hwnd):
        pid = U32()
        thread = self.user.GetWindowThreadProcessId(hwnd, C.byref(pid)) if hwnd else 0
        return {"pid": pid.value, "thread": thread}

    def layouts(self):
        count = self.user.GetKeyboardLayoutList(0, None)
        values = (HANDLE * max(1, count))()
        count = self.user.GetKeyboardLayoutList(len(values), values)
        return [int(values[i] or 0) for i in range(count)]

    def context(self, hwnd):
        result = {"hwnd": int(hwnd or 0), **self.process(hwnd)}
        himc = self.imm.ImmGetContext(hwnd) if hwnd else None
        result["himc"] = int(himc or 0)
        if not himc:
            return result
        try:
            for flag, label in ((0x0008, "composition"), (0x0800, "result")):
                length = self.imm.ImmGetCompositionStringW(himc, flag, None, 0)
                result[label + "_bytes"] = length
                if 0 < length <= 4096:
                    buffer = C.create_string_buffer(length)
                    actual = self.imm.ImmGetCompositionStringW(himc, flag, buffer, length)
                    if actual > 0:
                        result[label] = buffer.raw[:actual].decode("utf-16-le", errors="replace")
            conversion, sentence = U32(), U32()
            result["conversion_available"] = bool(self.imm.ImmGetConversionStatus(
                himc, C.byref(conversion), C.byref(sentence)))
            result["conversion"] = conversion.value
            result["sentence"] = sentence.value
            result["open"] = bool(self.imm.ImmGetOpenStatus(himc))
        finally:
            self.imm.ImmReleaseContext(hwnd, himc)
        return result

    def active_profile(self):
        """Read the GUI thread's active TSF keyboard profile, no activation."""
        init = self.ole.CoInitializeEx(None, 2)
        pointer = HANDLE()
        try:
            clsid = GUID.parse("33c53a50-f456-4884-b049-85fd643ecfed")
            iid = GUID.parse("71c6e74c-0f28-11d8-a82a-00065b84435c")
            hr = self.ole.CoCreateInstance(C.byref(clsid), None, 1, C.byref(iid), C.byref(pointer))
            if hr < 0 or not pointer:
                return {"available": False, "hresult": hex(hr & 0xffffffff)}
            table = C.cast(pointer, C.POINTER(C.POINTER(HANDLE))).contents
            category = GUID.parse("34745c63-b2f0-4784-8b67-5e12c8701a31")
            profile = Profile()
            # IUnknown's 3 methods + 7 methods before GetActiveProfile.
            get = C.WINFUNCTYPE(LONG, HANDLE, C.POINTER(GUID), C.POINTER(Profile))(table[10])
            hr = get(pointer, C.byref(category), C.byref(profile))
            if hr != 0:
                return {"available": False, "hresult": hex(hr & 0xffffffff)}
            return {"available": True, "type": profile.type, "langid": profile.langid,
                    "clsid": profile.clsid.text(), "profile": profile.profile.text(),
                    "hkl": int(profile.hkl or 0), "flags": profile.flags}
        finally:
            if pointer:
                table = C.cast(pointer, C.POINTER(C.POINTER(HANDLE))).contents
                C.WINFUNCTYPE(U32, HANDLE)(table[2])(pointer)
            if init >= 0:
                self.ole.CoUninitialize()

    def restore_context_mode(self, original):
        """Restore only the same test-owned context; never inject a toggle key."""
        hwnd = original["hwnd"]
        result = {"hwnd": hwnd, "attempted": False, "verified": False}
        if (self.process(hwnd) != {"pid": os.getpid(), "thread": self.kernel.GetCurrentThreadId()}
                or not original.get("conversion_available")):
            return {**result, "reason": "Original test context unavailable"}
        context = self.imm.ImmGetContext(hwnd)
        if not context:
            return {**result, "reason": "Original test HWND has no input context"}
        try:
            if int(context) != original["himc"]:
                return {**result, "reason": "Input context identity changed; no write attempted"}
            result.update(attempted=True,
                          open_call_succeeded=bool(self.imm.ImmSetOpenStatus(context, original["open"])),
                          conversion_call_succeeded=bool(self.imm.ImmSetConversionStatus(
                              context, original["conversion"], original["sentence"])))
        finally:
            self.imm.ImmReleaseContext(hwnd, context)
        after = self.context(hwnd)
        result["after"] = after
        result["verified"] = (after.get("conversion_available") is True
                              and all(after.get(key) == original[key] for key in ("open", "conversion", "sentence")))
        return result

    def guard_input(self, *, keyboard=True):
        if self.input_guard is None:
            raise Unavailable("No input ownership guard installed; input was not injected")
        self.input_guard(keyboard=keyboard)

    def send(self, items, *, release_owned_control=False):
        if release_owned_control:
            if (len(items) != 1 or items[0].type != 1 or items[0].ki.scan != 0x1d
                    or items[0].ki.flags != 0x000a):
                raise ValueError("Only the probe's own left Ctrl key-up may bypass focus checks")
        else:
            self.guard_input(keyboard=any(item.type == 1 for item in items))
        events = (Input * len(items))(*items)
        sent = self.user.SendInput(len(events), events, C.sizeof(Input))
        if sent != len(events):
            detail = {"sent": sent, "requested": len(events), "error": C.get_last_error()}
            # Every multi-event call in this probe is one down/up pair. If only
            # the down was accepted, try its matching release while ownership
            # still holds. Never send another key into a foreign application.
            if sent == 1 and len(items) == 2:
                try:
                    self.send([items[1]])
                    detail["matching_release"] = "delivered"
                except Exception as error:
                    detail["matching_release"] = f"not delivered: {type(error).__name__}: {error}"
            self.input_delivery_errors.append(detail)
            if sent:
                raise RuntimeError(f"Partial SendInput: {detail}")
            raise Unavailable(f"SendInput delivered no events: {detail}")

    def key(self, scan, *, down=True, extended=False, release_owned_control=False):
        flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if extended else 0)
        self.send([Input(type=1, ki=KeyInput(0, scan, flags, 0, 0))],
                  release_owned_control=release_owned_control)

    def tap(self, scan, *, extended=False):
        flags = 0x0008 | (0x0001 if extended else 0)
        self.send([Input(type=1, ki=KeyInput(0, scan, flags, 0, 0)),
                   Input(type=1, ki=KeyInput(0, scan, flags | 0x0002, 0, 0))])

    def click(self, x, y):
        self.guard_input(keyboard=False)
        if not self.user.SetCursorPos(x, y):
            raise Unavailable("SetCursorPos failed")
        self.send([Input(type=0, mi=MouseInput(0, 0, 0, 0x0002, 0, 0)),
                   Input(type=0, mi=MouseInput(0, 0, 0, 0x0004, 0, 0))])


def load_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def installed_korean_layouts():
    import winreg
    entries = []
    try:
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE,
                            r"SYSTEM\CurrentControlSet\Control\Keyboard Layouts") as layouts:
            for index in range(winreg.QueryInfoKey(layouts)[0]):
                name = winreg.EnumKey(layouts, index)
                if not name.lower().endswith("0412"):
                    continue
                item = {"klid": name}
                with winreg.OpenKey(layouts, name) as key:
                    for field in ("Layout Text", "Layout File", "Ime File", "Layout Display Name"):
                        try:
                            item[field] = winreg.QueryValueEx(key, field)[0]
                        except OSError:
                            pass
                entries.append(item)
    except OSError as error:
        return {"entries": entries, "error": str(error)}
    return {"entries": entries}


class Probe:
    def __init__(self, root, api, modules, report, *, allow_temporary_load=False,
                 allow_mode_toggle=False, preparation_seconds=0):
        self.root, self.api, self.modules, self.report = root, api, modules, report
        self.owner = self.chat = None
        self.events = []
        self.original_layout = api.user.GetKeyboardLayout(0)
        self.original_layouts = set(api.layouts())
        self.loaded_by_probe = set()
        self.allow_temporary_load = allow_temporary_load
        self.allow_mode_toggle = allow_mode_toggle
        self.preparation_seconds = preparation_seconds
        self.prepared = False
        self.mode_before_toggle = None
        self.api.input_guard = self.require_input_focus
        self.pressed_ctrl = False
        self.current_case = None
        self.any_composition = False
        self.started = time.monotonic()

    def foreground_owned(self):
        if self.chat is None:
            return False
        focus = self.api.user.GetForegroundWindow()
        own_thread = self.api.kernel.GetCurrentThreadId()
        own_root = self.api.user.GetAncestor(self.chat.winfo_id(), 2)
        if (not focus or self.api.process(focus) != {"pid": os.getpid(), "thread": own_thread}
                or self.api.user.GetAncestor(focus, 2) != own_root):
            return False
        native = self.api.user.GetFocus()
        return (self.api.process(native)["pid"] == os.getpid()
                and self.api.process(native)["thread"] == own_thread
                and self.api.user.GetAncestor(native, 2) == own_root)

    def require_input_focus(self, *, keyboard=True):
        if not self.foreground_owned():
            raise Unavailable("Probe lost its foreground/native focus; input was not injected")
        if keyboard and self.chat.focus_get() is not self.chat.input:
            raise Unavailable("Probe input Text no longer has logical focus; key was not injected")

    def release_control(self):
        if self.pressed_ctrl:
            self.api.key(0x1d, down=False, release_owned_control=True)
            self.pressed_ctrl = False

    def restore_case_mode(self):
        if self.mode_before_toggle is None:
            return
        original, self.mode_before_toggle = self.mode_before_toggle, None
        try:
            restored = self.api.restore_context_mode(original)
        except Exception as error:
            restored = {"attempted": True, "verified": False, "error": f"{type(error).__name__}: {error}"}
        self.current_case["ime_mode_restore"] = restored
        self.report.setdefault("ime_mode_cleanup", []).append(restored)
        if not restored.get("verified"):
            record_cleanup_failure(self.report, "Original IME mode could not be restored and verified")

    def snapshot(self, label):
        native = self.api.user.GetFocus()
        handles = {"text": self.chat.input.winfo_id(), "toplevel": self.chat.winfo_id(),
                   "native_focus": int(native or 0), "wrapper": self.api.user.GetAncestor(self.chat.winfo_id(), 2)}
        snap = {"label": label, "at": round(time.monotonic() - self.started, 4),
                "tk_focus": str(self.chat.focus_get()),
                "text": self.chat.input.get("1.0", "end-1c"),
                "hkl": int(self.api.user.GetKeyboardLayout(0) or 0),
                "foreground": int(self.api.user.GetForegroundWindow() or 0),
                "contexts": {key: self.api.context(hwnd) for key, hwnd in handles.items()},
                "control_state": self.api.user.GetKeyState(0x11),
                "control_async": self.api.user.GetAsyncKeyState(0x11),
                "alt_state": self.api.user.GetKeyState(0x12)}
        if self.current_case is not None:
            self.current_case["snapshots"].append(snap)
        return snap

    def observe_key(self, widget, char, state, send_event, keycode, keysym):
        # Observation only, before widget/class bindings; never inserts text.
        self.events.append({"at": round(time.monotonic() - self.started, 4), "widget": widget,
                            "char": char, "state": state, "send_event": send_event,
                            "keycode": keycode, "keysym": keysym})
        return ""

    def make_window(self, label, module):
        from assistant_ai.config import AISettings
        settings = AISettings(enabled=True)
        captures = []
        def capture(text, **kwargs):
            captures.append(text)
            return "로컬 IME 시험 응답 · 네트워크 없음"
        service = SimpleNamespace(
            load_settings=lambda: settings, ready=lambda: True,
            recent_turns=lambda **kw: [], chat=capture,
            cancel_chat=lambda event: event.set(), action_receipts=lambda *_: [],
            request_activity=lambda *_: "로컬 IME 시험", history_counts=lambda: {},
            ledger=SimpleNamespace(summary=lambda *_: SimpleNamespace(
                estimated_cost_usd=0, reserved_cost_usd=0)),
        )
        self.owner = module.AssistantWindows(self.root, service, context=lambda: {}, dispatch=lambda *_: {})
        self.owner.open_chat()
        self.chat = self.owner.chat_window
        self.chat.title("승아 입력 진단 · API 사용 없음 · " + label)
        import tkinter as tk
        self.notice = tk.Label(self.chat.body, text="한글 IME를 ‘가’ 모드로 선택해 주세요.\n"
                              "자동 검사 중에는 키보드·마우스를 사용하지 마세요. 실제 대화는 전송하지 않아요.",
                               font=(self.owner.font_family, 12), fg="#FFFFFF", bg="#5B3E00",
                               justify="left", wraplength=650, padx=12, pady=8)
        self.notice.pack(side="top", fill="x", before=self.chat.body.winfo_children()[0])
        self.chat.input.focus_force()
        self.api.user.SetForegroundWindow(self.api.user.GetAncestor(self.chat.winfo_id(), 2))
        tag = "ImeProbeObserver" + str(id(self.chat))
        command = self.chat.register(self.observe_key)
        self.chat.tk.call("bind", tag, "<KeyPress>", f"{command} %W %A %s %E %k %K")
        self.chat.input.bindtags((tag,) + self.chat.input.bindtags())
        return captures

    def clear_input_with_keys(self):
        if not self.foreground_owned():
            raise Unavailable("Probe lost foreground before reset; no keys injected")
        self.api.key(0x1d)
        self.pressed_ctrl = True
        self.api.tap(0x1e)  # Ctrl+A selects the draft through actual Tk bindings.
        self.release_control()
        self.api.tap(0x0e)  # Backspace, never Text.delete/insert.

    def prepare_composition(self):
        """A generator; GUI stays in its ordinary mainloop between actions."""
        layouts = self.api.layouts()
        korean = next((hkl for hkl in layouts if hkl & 0xffff == 0x0412), None)
        self.current_case["loaded_layouts"] = layouts
        if korean is None and self.allow_temporary_load:
            known = {entry["klid"].lower() for entry in self.report["installed_korean_layouts"]["entries"]}
            if "00000412" in known:
                if not self.foreground_owned():
                    raise Unavailable("Foreground changed before temporary layout load")
                # Windows 8+ loads/activates at system scope even with Flags=0.
                # This opt-in is for disposable CI only; no persistent language
                # list, override, reordering, or language pack is changed.
                loaded = int(self.api.user.LoadKeyboardLayoutW("00000412", 0) or 0)
                self.current_case["temporary_load_result"] = loaded
                if loaded and loaded not in self.original_layouts:
                    self.loaded_by_probe.add(loaded)
                yield 150
                if loaded & 0xffff == 0x0412:
                    korean = loaded
        if korean is None:
            raise Unavailable("No usable loaded Korean input locale (0412); see installed layouts and temporary-load policy")
        self.api.user.ActivateKeyboardLayout(korean, 0)  # Calling GUI thread only.
        yield 150
        if not self.foreground_owned():
            raise Unavailable("Probe does not own foreground/focus; no keyboard injection attempted")
        if int(self.api.user.GetKeyboardLayout(0) or 0) & 0xffff != 0x0412:
            raise Unavailable("Korean input locale activation did not take effect on GUI thread")
        self.current_case["active_tsf_profile"] = self.api.active_profile()
        profile = self.current_case["active_tsf_profile"]
        self.current_case["microsoft_korean_identity_verified"] = (
            profile.get("available") is True and profile.get("langid") == 0x0412
            and profile.get("clsid") == "a028ae76-01b1-46c2-99c4-acd9858ae02f"
            and profile.get("profile") == "b5fe1f02-d5f2-4445-9c03-c568f23c99a1"
        )
        desc = C.create_unicode_buffer(256)
        self.api.imm.ImmGetDescriptionW(self.api.user.GetKeyboardLayout(0), desc, 256)
        self.current_case["ime_description"] = desc.value

        # User PCs never receive an automatic A/가 toggle. CI may explicitly
        # opt in; preserve the original mode before any such state change.
        for attempt in range(2 if self.allow_mode_toggle else 1):
            if attempt:
                self.clear_input_with_keys()
                yield 100
                original = self.api.context(self.api.user.GetFocus())
                if not original.get("himc") or not original.get("conversion_available"):
                    raise Unavailable("Cannot snapshot IME mode for restoration; no automatic mode toggle attempted")
                self.mode_before_toggle = original
                self.current_case["ime_mode_before_toggle"] = original
                self.api.tap(0x38, extended=True)  # Physical right Alt / Hangul toggle.
                yield 150
            self.api.tap(0x2c)  # Physical Z in two-set Korean creates ㅋ.
            for poll in range(40):
                yield 20
                if not self.foreground_owned():
                    raise Unavailable("Foreground changed during Korean input; remaining injection stopped")
                snap = self.snapshot(f"composition-{attempt}-{poll}")
                active = [entry for entry in snap["contexts"].values()
                          if entry.get("composition_bytes", 0) > 0 and entry.get("composition") == "ㅋ"]
                if active:
                    self.current_case["real_composition_observed"] = True
                    self.current_case["composition_hwnds"] = [entry["hwnd"] for entry in active]
                    self.any_composition = True
                    return
        raise Unavailable("실제 한글 조합을 확인하지 못했어요. 한글 IME를 ‘가’ 모드로 선택한 뒤 다시 실행해 주세요. "
                          "SendInput Z did not produce COMPSTR=ㅋ; no pass is claimed")

    def run(self):
        for label, module in self.modules:
            variant = {"name": label, "cases": []}
            self.report["variants"].append(variant)
            for scenario, hold_ms in (("ctrl_return", 0), ("ctrl_return", 50),
                                      ("ctrl_return", 250), ("button", 0), ("plain_return", 0)):
                case = {"scenario": scenario, "ctrl_hold_ms": hold_ms, "snapshots": [],
                        "real_composition_observed": False}
                self.current_case = case
                variant["cases"].append(case)
                self.events = []
                captures = self.make_window(label, module)
                try:
                    if not self.prepared:
                        for remaining in range(self.preparation_seconds, 0, -1):
                            self.notice.configure(text=f"{remaining}초 뒤 자동 검사를 시작해요. 한글 IME를 ‘가’ 모드로 선택하고\n"
                                                  "입력칸에 커서를 둔 뒤 키보드·마우스에서 손을 떼 주세요. API는 사용하지 않아요.")
                            yield 1000
                        self.prepared = True
                    self.notice.configure(text="자동 입력 검사 중 · 키보드·마우스를 사용하지 마세요.\n"
                                          "고정된 ‘ㅋ’만 로컬에서 확인하며 실제 대화/API 전송은 없어요.")
                    yield 250
                    if not self.foreground_owned():
                        raise Unavailable("Cannot acquire own chat foreground/native focus")
                    if any(self.api.user.GetAsyncKeyState(key) & 0x8000
                           for key in (0x01, 0x02, 0x04, 0x10, 0x11, 0x12, 0x5b, 0x5c)):
                        raise Unavailable("A mouse button or modifier is held; release it before starting the probe")
                    self.snapshot("before-composition")
                    yield from self.prepare_composition()
                    self.snapshot("before-submit")
                    if scenario == "button":
                        button = self.chat.send_button
                        self.api.click(button.winfo_rootx() + button.winfo_width() // 2,
                                       button.winfo_rooty() + button.winfo_height() // 2)
                    elif scenario == "ctrl_return":
                        self.api.key(0x1d)
                        self.pressed_ctrl = True
                        yield 20
                        self.snapshot("control-held-before-return")
                        if not self.foreground_owned():
                            raise Unavailable("Foreground changed while Ctrl was held; Enter was not injected")
                        self.api.tap(0x1c)
                        yield max(1, hold_ms)
                        self.snapshot("before-control-release")
                        self.release_control()
                    else:
                        self.api.tap(0x1c)
                        yield 300
                        first = self.snapshot("after-first-plain-return")
                        case["after_first_return"] = first["text"]
                        case["composition_after_first_return"] = any(
                            value.get("composition_bytes", 0) > 0 for value in first["contexts"].values())
                        self.api.tap(0x1c)
                        yield 300
                    if scenario != "plain_return":
                        for index in range(65):
                            yield 100
                            if captures and self.owner._cancel is None:
                                break
                    yield 200  # Check late insertion/remaining preedit after local completion.
                    final = self.snapshot("after-submit")
                    pending_composition = any(value.get("composition_bytes", 0) > 0
                                              for value in final["contexts"].values())
                    case["composition_after_submit"] = pending_composition
                    passed = (captures == ["ㅋ"] and final["text"] == "" and not pending_composition)
                    if scenario == "plain_return":
                        passed = (captures == [] and case["after_first_return"] in {"ㅋ", "ㅋ\n"}
                                  and not case["composition_after_first_return"]
                                  and final["text"] == case["after_first_return"] + "\n" and not pending_composition)
                    case.update(captured=captures[:], remaining_draft=final["text"],
                                ui_status=self.chat.status.get(), key_events=self.events[:],
                                status="passed" if passed else "failed")
                    if case["status"] == "failed":
                        case["reason"] = ("Expected plain Return to preserve ㅋ, send nothing, then insert a newline"
                                          if scenario == "plain_return" else
                                          "Expected exactly one complete ㅋ captured by local fake service and no residual draft")
                except Unavailable as error:
                    case.update(status="unavailable", reason=str(error), key_events=self.events[:])
                    variant["status"] = ("failed" if any(c.get("status") == "failed" for c in variant["cases"])
                                         else "unavailable")
                    # A machine without the required input environment cannot
                    # gain useful evidence by trying more submission paths.
                    return
                finally:
                    self.release_control()
                    self.restore_case_mode()
                    self.owner.close()
                    self.owner = self.chat = None
                yield 150
            variant["status"] = "passed" if all(c["status"] == "passed" for c in variant["cases"]) else "failed"

    def drive(self, generator):
        try:
            delay = next(generator)
        except StopIteration:
            self.finish()
        except Exception as error:
            self.report.update(status="failed", reason=f"Probe error: {type(error).__name__}: {error}",
                               traceback=traceback.format_exc())
            self.finish()
        else:
            self.root.after(delay, self.drive, generator)

    def finish(self):
        for cleanup in (self.release_control, self.restore_case_mode):
            try:
                cleanup()
            except Exception as error:
                record_cleanup_failure(self.report, f"{cleanup.__name__}: {type(error).__name__}: {error}")
        if self.original_layout:
            try:
                self.api.user.ActivateKeyboardLayout(self.original_layout, 0)
                actual = int(self.api.user.GetKeyboardLayout(0) or 0)
                self.report["layout_restore"] = {"expected": int(self.original_layout), "actual": actual,
                                                 "verified": actual == int(self.original_layout)}
                if actual != int(self.original_layout):
                    record_cleanup_failure(self.report, "Original keyboard layout could not be restored")
            except Exception as error:
                record_cleanup_failure(self.report, f"Layout restore: {type(error).__name__}: {error}")
        self.report["layout_cleanup"] = []
        for hkl in self.loaded_by_probe:
            try:
                unloaded = bool(self.api.user.UnloadKeyboardLayout(hkl))
                self.report["layout_cleanup"].append({"hkl": hkl, "unloaded": unloaded})
                if not unloaded:
                    record_cleanup_failure(self.report, f"Temporary keyboard layout {hkl} could not be unloaded")
            except Exception as error:
                record_cleanup_failure(self.report, f"Layout unload: {type(error).__name__}: {error}")
        try:
            if self.owner:
                self.owner.close()
        except Exception as error:
            record_cleanup_failure(self.report, f"Window close: {type(error).__name__}: {error}")
        finally:
            self.root.quit()


def record_cleanup_failure(report, reason):
    report.setdefault("cleanup_errors", []).append(reason)
    if report["status"] != "failed":
        report.update(input_test_status=report["status"], status="failed", reason=reason)


def write_report(report, path):
    """Keep a failed requested write distinct from the input-test result."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return True
    except OSError as error:
        report.update(input_test_status=report["status"], status="failed",
                      reason=f"진단 보고서를 요청한 경로에 저장하지 못했어요: {error}",
                      requested_report=str(path))
        try:
            with tempfile.NamedTemporaryFile(prefix="seunga-ime-report-", suffix=".json", mode="w",
                                             encoding="utf-8", delete=False) as fallback:
                report["fallback_report"] = fallback.name
                json.dump(report, fallback, ensure_ascii=False, indent=2)
                fallback.write("\n")
        except OSError as fallback_error:
            report["fallback_error"] = str(fallback_error)
        return False


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path.cwd())
    parser.add_argument("--baseline-ime", type=Path)
    parser.add_argument("--baseline-ui", type=Path)
    parser.add_argument("--allow-temporary-layout-load", action="store_true",
                        help="Disposable Windows CI only: temporarily load installed 00000412 (system scope on Windows 8+), then restore/unload")
    parser.add_argument("--allow-ime-mode-toggle", action="store_true",
                        help="Disposable CI only: allow a right-Alt A/가 toggle, then attempt and verify mode restoration")
    parser.add_argument("--manual-preparation-seconds", type=int, default=0,
                        help="Allow 0–30 seconds to select Korean 가 mode before the first input injection")
    args = parser.parse_args(argv)
    if not 0 <= args.manual_preparation_seconds <= 30:
        parser.error("--manual-preparation-seconds must be between 0 and 30")
    report = {"status": "unavailable", "started_at": datetime.now(timezone.utc).isoformat(),
              "platform": platform.platform(), "python": sys.version, "variants": [],
              "network_attempts": 0, "real_api_calls": 0,
              "ime_mode_toggle_allowed": args.allow_ime_mode_toggle,
              "manual_preparation_seconds": args.manual_preparation_seconds,
              "evidence_kind": "real SendInput scan-code -> Korean IMM composition -> actual ChatWindow -> local capture",
              "limitations": ["A single isolated ㅋ is a minimal reproduction, not full user-message reproduction.",
                              "No claim about user's installed version, hardware, or Windows client IME is made.",
                              "Optional temporary layout loading has system scope on Windows 8+; intended only for disposable CI. No persistent language settings or packages are changed."]}
    if os.name != "nt":
        report["reason"] = "Windows required; actual Korean IME unverified"
    else:
        profile = tempfile.TemporaryDirectory(prefix="seunga-ime-probe-", ignore_cleanup_errors=True)
        original_appdata = os.environ.get("APPDATA")
        os.environ["APPDATA"] = profile.name
        report["isolated_appdata"] = profile.name
        os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        original_path = sys.path[:]
        if not getattr(sys, "frozen", False):
            sys.path.insert(0, str(args.repo.resolve()))
        def blocked_network(*_args, **_kwargs):
            report["network_attempts"] += 1
            raise RuntimeError("Network is prohibited in the IME probe")
        original_create_connection, original_connect = socket.create_connection, socket.socket.connect
        socket.create_connection, socket.socket.connect = blocked_network, blocked_network
        root = None
        try:
            import tkinter as tk
            from assistant_ai import ui
            modules = [("current", ui)]
            if args.baseline_ui and args.baseline_ime:
                old_ime = load_file("assistant_ai.ime_probe_baseline_adapter", args.baseline_ime)
                old_ui = load_file("assistant_ai.ui_probe_baseline", args.baseline_ui)
                old_ui.prepare_input = old_ime.prepare_input
                modules.append(("baseline_2_1_4", old_ui))
                report["baseline_sha256"] = {"ui": hashlib.sha256(args.baseline_ui.read_bytes()).hexdigest(),
                                             "ime": hashlib.sha256(args.baseline_ime.read_bytes()).hexdigest()}
            api = WinAPI()
            report["input_delivery_errors"] = api.input_delivery_errors
            session = U32()
            api.kernel.ProcessIdToSessionId(os.getpid(), C.byref(session))
            report.update(pid=os.getpid(), gui_thread=api.kernel.GetCurrentThreadId(), session=session.value,
                          input_struct_bytes=C.sizeof(Input), loaded_layouts=api.layouts(),
                          installed_korean_layouts=installed_korean_layouts(),
                          temporary_layout_load_allowed=args.allow_temporary_layout_load)
            if session.value == 0:
                raise Unavailable("Session 0 is not an interactive user desktop")
            root = tk.Tk()
            root.withdraw()
            report["tk_patchlevel"] = root.tk.call("package", "provide", "Tk")
            probe = Probe(root, api, modules, report, allow_temporary_load=args.allow_temporary_layout_load,
                          allow_mode_toggle=args.allow_ime_mode_toggle,
                          preparation_seconds=args.manual_preparation_seconds)
            root.after(20, probe.drive, probe.run())
            root.mainloop()
            if report["status"] != "failed":
                current = next((variant for variant in report["variants"] if variant["name"] == "current"), {})
                report["status"] = current.get("status", "unavailable")
                if report["status"] == "unavailable":
                    report["reason"] = next((case.get("reason") for case in current.get("cases", [])
                                             if case.get("status") == "unavailable"), "Current real-IME evidence unavailable")
                elif report["status"] == "failed":
                    report["reason"] = "Current ChatWindow failed at least one real-composition transmission case"
            report["real_composition_observed"] = probe.any_composition
            report["microsoft_korean_identity_verified"] = any(
                case.get("microsoft_korean_identity_verified") for variant in report["variants"]
                for case in variant["cases"] if case.get("real_composition_observed"))
        except Unavailable as error:
            report.update(status="unavailable", reason=str(error))
        except Exception as error:
            report.update(status="failed", reason=f"Probe error: {type(error).__name__}: {error}",
                          traceback=traceback.format_exc())
        finally:
            try:
                if root is not None:
                    root.destroy()
            except Exception as error:
                record_cleanup_failure(report, f"Window cleanup: {type(error).__name__}: {error}")
            try:
                # The UI may initialize a rotating app log inside this
                # process's temporary profile. Close it before Windows tries
                # to remove the directory, including the packaged entrypoint.
                logging.shutdown()
                profile.cleanup()
            except Exception as error:
                record_cleanup_failure(report, f"Temporary profile cleanup: {type(error).__name__}: {error}")
            finally:
                socket.create_connection, socket.socket.connect = original_create_connection, original_connect
                sys.path[:] = original_path
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata
    if report["network_attempts"]:
        report.update(status="failed", reason="A prohibited network attempt was blocked")
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    written = write_report(report, args.report)
    print(json.dumps({"status": report["status"], "reason": report.get("reason"),
                      "report": str(args.report) if written else report.get("fallback_report")}, ensure_ascii=False))
    if not written and os.name == "nt" and getattr(sys, "frozen", False):
        # A windowed executable has no console to show the write failure.
        user = C.WinDLL("user32", use_last_error=True)
        user.MessageBoxW.argtypes = (HANDLE, C.c_wchar_p, C.c_wchar_p, U32)
        user.MessageBoxW.restype = C.c_int
        fallback = report.get("fallback_report", "임시 경로에도 저장하지 못했어요.")
        user.MessageBoxW(None, report["reason"] + "\n\n" + fallback, "승아 입력 진단 · 보고서 저장 실패", 0x10)
    return {"passed": 0, "failed": 1, "unavailable": 3}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
