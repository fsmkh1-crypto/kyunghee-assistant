"""Exercise the packaged GUI without network requests or a real user profile."""
from __future__ import annotations

import json
import faulthandler
import os
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch


def _click_full_reply(desktop, count=1):
    """Use the same native click target as the shipped Windows widget."""
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        hitbox = desktop._chat_hitbox
        assert hitbox is not None and hitbox._hwnd, "reply click target unavailable"
        send = ctypes.WinDLL("user32").PostMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = wintypes.BOOL
        for _ in range(count):
            assert send(hitbox._hwnd, 0x0201, 1, 4 | (4 << 16)), "native click was not queued"
    else:
        for _ in range(count):
            desktop._visible_speech().event_generate("<Button-1>", x=4, y=4)
    # PostMessage enters through Tk's OS event pump, as a physical click does.
    # SendMessage from Python bypasses that boundary and missed the fatal bug.
    desktop.root.after(100, desktop.root.quit)
    desktop.root.mainloop()
    desktop.root.update()


def _exercise_full_reply(desktop):
    root, windows = desktop.root, desktop._assistant_windows
    reply = ("긴 답변 보존 검사 — 한글과 emoji 🙂, 줄바꿈도 그대로 읽을 수 있어야 해요.\n" * 120
             + "https://example.com/reference\n마지막 문장입니다.")
    memory = desktop._assistant_service.memory
    memory.set_history_enabled(True)
    memory.set_enabled(True)
    turn_id = memory.begin_turn("기존 대화 보존 검사")
    assert memory.finish_turn(turn_id, reply)
    memory.add_memory("전체보기는 저장된 기억을 변경하지 않는다")
    saved_turns, saved_counts = memory.recent_turns(None), memory.counts()
    windows.open_chat()
    draft = "아직 보내지 않은 초안"
    windows.chat_window.input.insert("1.0", draft)
    windows.chat_window.input.edit_modified(False)
    root.update()

    reader = None
    for close_kind in ("button", "escape", "titlebar", "repeat"):
        desktop._show_chat_phase("reply", reply)
        root.update()
        assert desktop._expandable_reply == reply, "long answer was not folded"
        _click_full_reply(desktop, count=3 if close_kind == "repeat" else 1)
        current = windows.reply_window
        assert current is not None and current.winfo_viewable(), "full answer did not open"
        if reader is not None:
            assert current is reader, "reopening created duplicate reply windows"
        reader = current
        assert reader.text.get("1.0", "end-1c") == reply, "full answer was truncated or changed"
        assert reader.text.tag_ranges("source"), "source link unavailable in full answer"
        assert reader.winfo_width() <= root.winfo_screenwidth(), "full answer exceeds display width"
        assert reader.winfo_height() <= root.winfo_screenheight(), "full answer exceeds display height"
        if close_kind == "button":
            close = next(widget for widget in reader.actions.winfo_children()
                         if widget.cget("text") == "닫기")
            close.invoke()
        elif close_kind == "escape":
            reader.text.focus_force()
            root.update()
            reader.text.event_generate("<Escape>")
        else:
            reader.tk.call(reader.protocol("WM_DELETE_WINDOW"))
        root.update()
        assert reader.state() == "withdrawn", "closing full answer did not hide its window"
        assert root.winfo_exists(), "closing full answer destroyed the timer"

    windows.open_reply(reply)
    resume = next(widget for widget in reader.actions.winfo_children()
                  if widget.cget("text") == "대화 계속하기")
    resume.invoke()
    root.update()
    assert windows.chat_window.winfo_viewable(), "continue chat did not reopen the conversation"
    assert windows.chat_window.input.get("1.0", "end-1c") == draft, "existing draft was modified"
    assert memory.recent_turns(None) == saved_turns, "full answer modified saved conversations"
    assert memory.counts() == saved_counts, "full answer modified saved data"
    heartbeat = []
    root.after(1, lambda: heartbeat.append(True))
    root.after(25, root.quit)
    root.mainloop()
    assert heartbeat, "timer event loop stopped after opening full answer"


def run_packaged_smoke(app_factory, report_path):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"status":"running"}', encoding="utf-8")
    with report_path.with_suffix(".fault.log").open("w", encoding="utf-8") as fault_log:
        faulthandler.enable(file=fault_log, all_threads=True)
        try:
            return _run_packaged_smoke(app_factory, report_path)
        finally:
            faulthandler.disable()


def _run_packaged_smoke(app_factory, report_path):
    import tkinter as tk
    import app
    import desktop_compact as compact
    from settings import UserSettings, save_user_settings
    from workday import WorkdayState
    from app_brand import APP_VERSION

    report = {"version": APP_VERSION, "api_calls": 0, "isolated_profile": True, "checks": []}
    compact.enable_per_monitor_dpi_awareness()
    create_tk = tk.Tk
    try:
        for dpi in (96, 120, 144, 192):
            with tempfile.TemporaryDirectory(prefix="seunga-packaged-smoke-") as temporary:
                directory = Path(temporary)
                settings_file = directory / "settings.json"
                save_user_settings(settings_file, UserSettings(welcome_seen=True, builtin_image_set="01"))

                def root_at_dpi():
                    root = create_tk()
                    root.tk.call("tk", "scaling", dpi / 72)
                    root.report_callback_exception = lambda kind, value, tb: callback_errors.append(
                        "".join(traceback.format_exception(kind, value, tb)))
                    return root

                callback_errors = []
                with (
                    patch.multiple(app, DATA_DIR=directory, SETTINGS_FILE=settings_file,
                                   STATE_FILE=directory / "state.json"),
                    patch.multiple(compact, USER_IMAGE_DIR=directory / "images",
                                   USER_IMAGE_SET_DIR=directory / "image_sets"),
                    patch.object(app.App, "_start_tray"),
                    patch.object(app.App, "_current_workday_state", lambda self: WorkdayState("normal", None)),
                    patch.object(compact.CompactDesktopApp, "_start_global_hotkey"),
                    patch.multiple(app_factory, MANUAL_OVERRIDE_FILE=directory / "manual_asset_overrides.json",
                                   GALLERY_RANDOM_FILE=directory / "gallery_random_shuffle.json",
                                   IMPORTED_ASSET_DIR=directory / "imported_assets"),
                    patch.object(tk, "Tk", root_at_dpi),
                    patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("network is disabled in packaged smoke")) as network,
                ):
                    desktop = app_factory()
                    try:
                        root = desktop.root
                        root.update()
                        assert desktop.random_gallery_control.winfo_viewable(), "screen dice missing"
                        desktop._show_page("settings")
                        root.update()
                        assert len(desktop._settings_notebook.tabs()) == 4, "settings tabs missing"
                        footer = desktop.settings_dirty_label
                        assert footer.winfo_viewable(), "settings save footer hidden"
                        assert 0 <= footer.winfo_rooty() - root.winfo_rooty() < root.winfo_height(), "footer outside screen"
                        desktop.state.session.is_away = True
                        desktop._set_character("away")
                        desktop._show_page("timer")
                        root.update()
                        assert desktop.character_role == "away", "page transition lost away pose"
                        windows = desktop._assistant_windows
                        assert windows is not None, "assistant failed to initialize"
                        _exercise_full_reply(desktop)
                        windows.open_chat()
                        windows.open_settings()
                        windows.open_memories()
                        windows.open_image_picker()
                        desktop._open_asset_gallery("default")
                        desktop._open_data_panel()
                        with patch.object(desktop._assistant_service, "weather_report", return_value="테스트 날씨 · 외부 요청 없음"):
                            windows.open_weather("테스트 지역")
                            root.after(100, root.quit)
                            root.mainloop()
                        root.update()
                        assert windows.chat_window.winfo_exists(), "chat unavailable"
                        assert windows.settings_window.winfo_viewable(), "AI settings unavailable"
                        for window in (item for item in root.winfo_children() if isinstance(item, tk.Toplevel)):
                            assert window.winfo_width() <= root.winfo_screenwidth(), "dialog exceeds display width"
                            assert window.winfo_height() <= root.winfo_screenheight(), "dialog exceeds display height"
                        status = desktop._assistant_service.local_status(desktop._assistant_tools.context())
                        assert isinstance(status, str) and status, "offline status unavailable"
                        proposal = desktop.propose_image_action({"kind": "base_set", "set_id": "01"})
                        assert proposal["status"] == "pending", "image proposal unavailable"
                        assert desktop.cancel_image_action(proposal["id"])["status"] == "cancelled"
                        assert network.call_count == 0, "unexpected network request"
                        assert not callback_errors, "Tk callback failed:\n" + "\n".join(callback_errors)
                        report["checks"].append({"dpi": dpi, "status": "passed",
                                                 "flows": ["dice", "settings", "away", "full reply native click", "reply close/reopen/repeat", "conversation and draft preservation", "chat", "AI settings", "memories", "image picker", "gallery", "backup", "weather", "offline status", "image cancel"]})
                    finally:
                        for timer_id in root.tk.splitlist(root.tk.call("after", "info")):
                            root.tk.call("after", "cancel", timer_id)
                        desktop.quit()
        report["status"] = "passed"
    except Exception:
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
