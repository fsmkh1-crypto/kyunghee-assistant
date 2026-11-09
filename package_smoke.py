"""Exercise the packaged GUI without network requests or a real user profile."""
from __future__ import annotations

import json
import faulthandler
import os
from pathlib import Path
import tempfile
import time
import traceback
from unittest.mock import patch


def _click_inline_reply(desktop, count=1):
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


def _descendants(widget):
    for child in widget.winfo_children():
        yield child
        yield from _descendants(child)


def _assert_action_visible(button, window):
    assert button.winfo_viewable(), f"{button.cget('text')} action is hidden"
    x, y = button.winfo_rootx() - window.winfo_rootx(), button.winfo_rooty() - window.winfo_rooty()
    geometry = (x, y, button.winfo_width(), button.winfo_height(), window.winfo_width(), window.winfo_height())
    assert 0 <= x and x + button.winfo_width() <= window.winfo_width(), f"action exceeds dialog width: {geometry}"
    assert 0 <= y and y + button.winfo_height() <= window.winfo_height(), f"action exceeds dialog height: {geometry}"
    assert button.winfo_height() >= button.winfo_reqheight(), "action height is clipped"


def _exercise_approval_actions(desktop, progress=lambda _phase: None):
    root, windows = desktop.root, desktop._assistant_windows
    resize_samples = []
    with patch.object(windows, "chat_work_area", lambda *_args: (0, 0, 640, 360)):
        for action in ("취소", "적용"):
            progress("timer approval: " + action)
            errors, clicked = [], []
            deadline = time.monotonic() + 5

            def sample(dialog):
                button = dialog.apply_button
                return {"window": [dialog.winfo_width(), dialog.winfo_height()],
                        "apply": [button.winfo_rootx() - dialog.winfo_rootx(),
                                  button.winfo_rooty() - dialog.winfo_rooty(),
                                  button.winfo_width(), button.winfo_height()]}

            def verify_and_click(dialog, initial):
                try:
                    resize_samples.append({"action": action, "after_idle": initial, "after_events": sample(dialog)})
                    buttons = {item.cget("text"): item for item in _descendants(dialog)
                               if item.winfo_class() == "Button"}
                    for label in ("적용", "취소"):
                        _assert_action_visible(buttons[label], dialog)
                    assert dialog.description.winfo_viewable(), "approval description is hidden"
                    assert dialog.description.winfo_height() > 24, "approval description has no readable area"
                    clicked.append(action)
                    buttons[action].invoke()
                except Exception:
                    errors.append(traceback.format_exc())
                    dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

            def wait_for_resize(dialog, initial, previous=None):
                current = sample(dialog)
                if current["window"] == [360, 240] and current == previous:
                    verify_and_click(dialog, initial)
                elif time.monotonic() >= deadline - 0.2:
                    errors.append(f"approval resize did not settle: {current}")
                    dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))
                else:
                    root.after(20, lambda: wait_for_resize(dialog, initial, current))

            def click_action():
                found = [item for item in root.winfo_children()
                         if item.winfo_class() == "Toplevel" and item.title().startswith("승아 요청 확인")]
                if not found:
                    if time.monotonic() < deadline:
                        root.after(30, click_action)
                    return
                dialog = found[-1]
                try:
                    dialog.geometry("360x240")
                    dialog.update_idletasks()
                    # WM resize messages must pass through the OS event pump.
                    # update_idletasks alone can still report the old child
                    # positions with the new window size on Windows.
                    initial = sample(dialog)
                    root.after(20, lambda: wait_for_resize(dialog, initial))
                except Exception:
                    errors.append(traceback.format_exc())
                    dialog.tk.call(dialog.protocol("WM_DELETE_WINDOW"))

            root.after(50, click_action)
            approved = desktop._confirm_assistant_change(
                "휴식 상태로 바꿉니다. 내용을 확인한 뒤 적용하세요.\n" * 50,
                lambda: time.monotonic() >= deadline,
            )
            assert not errors, "approval layout failed:\n" + "\n".join(errors)
            assert clicked == [action], "approval action was not reached"
            assert approved == (action == "적용"), "approval result changed"

        proposal = desktop.propose_image_action({"kind": "base_set", "set_id": "01"})
        progress("image approval: show")
        windows.show_image_proposal({**proposal, "summary": "이미지 변경 확인 " * 30,
                                     "scope": "변경 범위를 확인한 뒤 적용합니다. " * 30})
        dialog = next(item for item in root.winfo_children()
                      if item.winfo_class() == "Toplevel" and item.title().startswith("이미지 변경 확인"))
        dialog.geometry("360x240")
        progress("image approval: resize event pump")
        root.update()
        progress("image approval: inspect")
        buttons = {item.cget("text"): item for item in _descendants(dialog)
                   if item.winfo_class() == "Button"}
        for label in ("적용", "취소", "되돌리기"):
            _assert_action_visible(buttons[label], dialog)
        assert dialog.content_canvas.winfo_viewable(), "image approval details are hidden"
        buttons["취소"].invoke()
        assert dialog.state() == "withdrawn", "image cancellation did not close the proposal"
    return resize_samples


def _exercise_away_clock(desktop):
    from copy import deepcopy
    from types import SimpleNamespace
    from timer_engine import TimerEngine

    state = deepcopy(desktop.state)
    state.session.is_away = state.session.manual_away = False
    clock = SimpleNamespace(mono=100.0, wall=time.time(), idle=0.0)
    engine = TimerEngine(state, clock=lambda: clock.mono, wall=lambda: clock.wall,
                         idle_provider=lambda: (clock.idle, 1))
    before_away, before_active = state.daily.away_seconds, state.daily.active_seconds
    with patch.object(desktop, "state", state), patch.object(desktop, "engine", engine):
        engine.start_manual_away()
        for elapsed in (2, 3):
            clock.mono += elapsed
            clock.wall += elapsed
            clock.idle += elapsed
            engine.tick()
            desktop._update_ui()
            assert desktop.cont.cget("text") == f"00:00:{int(clock.idle):02d}", "away clock stopped"
            assert state.daily.away_seconds == before_away + clock.idle, "away records drifted"
            assert state.daily.active_seconds == before_active, "away counted as active"
            assert state.session.continuous_seconds == 0, "away changed focus streak"
    desktop._update_ui()


def _exercise_preview_navigation(desktop):
    from dataclasses import asdict
    from PIL import ImageTk

    desktop._show_page("settings")
    desktop._settings_notebook.select(2)
    desktop._select_settings_preview("default")
    desktop.root.update()
    before_settings = asdict(desktop.preferences)
    before = ImageTk.getimage(desktop.settings_preview_image.image).tobytes()
    before_label = desktop.settings_preview_meta.cget("text")
    desktop.settings_preview_next.invoke()
    desktop.root.update()
    assert desktop.settings_preview_meta.cget("text") != before_label, "preview navigation did not advance"
    assert ImageTk.getimage(desktop.settings_preview_image.image).tobytes() != before, "preview pixels did not change"
    desktop.settings_preview_prev.invoke()
    desktop.root.update()
    assert desktop.settings_preview_meta.cget("text") == before_label, "previous preview was not restored"
    assert asdict(desktop.preferences) == before_settings, "preview navigation modified saved preferences"

    # Previewing another role is intentionally different from applying that
    # file to the selected role. Exercise the visible Apply control itself.
    before_image_state = desktop._image_action_state()
    for _ in range(len(desktop.IMAGE_ROWS)):
        if desktop._settings_preview_current_path.name.startswith("settings_"):
            break
        desktop.settings_preview_next.invoke()
    selected = desktop._settings_preview_current_path
    assert selected.name.startswith("settings_"), "cross-role preview is unavailable"
    assert desktop._image_action_state() == before_image_state, "preview silently applied an image"
    button = desktop._settings_preview_apply_button
    button.focus_force()
    desktop.root.update()
    x, y = button.winfo_width() // 2, button.winfo_height() // 2
    assert button.winfo_viewable(), "preview Apply is hidden"
    hit = desktop.root.winfo_containing(button.winfo_rootx() + x, button.winfo_rooty() + y)
    assert hit is button, "preview Apply is covered by another widget"
    was_away = desktop.state.session.is_away
    button.event_generate("<Motion>", x=x, y=y, warp=True)
    button.event_generate("<Enter>", x=x, y=y)
    button.event_generate("<ButtonPress-1>", x=x, y=y)
    desktop.root.update()
    button.event_generate("<ButtonRelease-1>", x=x, y=y)
    desktop.root.update()
    assert desktop._manual_override_path("default") == selected, "Apply did not assign the preview to the selected role"
    assert desktop.state.session.is_away == was_away, "image Apply changed timer state"
    assert selected.name in desktop._image_applied_label.cget("text"), "applied filename is missing"
    desktop.undo_image_action()
    assert desktop._image_action_state() == before_image_state, "image Undo did not restore the previous selection"
    desktop._show_page("timer")


def _exercise_inline_reply(desktop, progress=lambda _phase: None):
    root, windows = desktop.root, desktop._assistant_windows
    reply = ("긴 답변 보존 검사 — 한글과 emoji 🙂, 줄바꿈도 그대로 읽을 수 있어야 해요.\n" * 120
             + "https://example.com/reference\n마지막 문장입니다.")
    memory = desktop._assistant_service.memory
    memory.set_history_enabled(True)
    memory.set_enabled(True)
    turn_id = memory.begin_turn("기존 대화 보존 검사")
    assert memory.finish_turn(turn_id, reply)
    memory.add_memory("말풍선 스크롤은 저장된 기억을 변경하지 않는다")
    saved_turns, saved_counts = memory.recent_turns(None), memory.counts()
    windows.open_chat()
    draft = "아직 보내지 않은 초안"
    windows.chat_window.input.insert("1.0", draft)
    windows.chat_window.input.edit_modified(False)
    root.update()
    windows._set_chat_state("reply", reply)
    windows.chat_window._hide()
    root.update()
    bubble = desktop._visible_speech()
    progress("inline reply: original text and native repeated clicks")
    assert bubble.cget("text") == reply, "bubble truncated the original reply"
    assert bubble.text_widget.get("1.0", "end-1c") == reply, "scrollable text lost content"
    assert int(bubble.text_widget.cget("height")) <= 3, "speech viewport exceeds three lines"
    assert bubble.scrollbar.winfo_viewable(), "long reply has no scrollbar"
    _click_inline_reply(desktop, count=3)
    assert windows.reply_window is None or not windows.reply_window.winfo_viewable(), "bubble opened a separate reader"
    assert not windows.chat_window.winfo_viewable(), "reading opened chat unexpectedly"
    bubble.scroll_to(0)
    root.update()
    before = bubble.text_widget.yview()
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes
        send = ctypes.WinDLL("user32").PostMessageW
        send.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        send.restype = wintypes.BOOL
        # Exercise wheel dispatch through the same native callback boundary as
        # real OS input; the callback must enqueue plain data, never call Tk.
        assert send(desktop._chat_hitbox._hwnd, 0x020A, (0xFF88 << 16), 0)
        root.after(100, root.quit)
        root.mainloop()
    else:
        bubble.text_widget.event_generate("<Button-5>")
    root.update()
    assert bubble.text_widget.yview()[0] > before[0], "wheel did not scroll the inline reply"
    progress("inline reply: scrollbar and keyboard")
    bubble.scroll_to(1)
    root.update()
    assert bubble.text_widget.yview()[1] >= 0.999, "last line is unreachable"
    # Earlier modal/chat windows have been withdrawn. Model the user bringing
    # the timer to the foreground before exercising its keyboard bindings.
    root.focus_force()
    bubble.focus_reading()
    root.update()
    bubble.text_widget.event_generate("<Control-Home>")
    root.update()
    assert bubble.text_widget.yview()[0] == 0, "keyboard cannot return to the start"
    bubble.text_widget.event_generate("<Next>")
    root.update()
    assert bubble.text_widget.yview()[0] > 0, "Page Down did not scroll"
    assert bubble.text_widget.cget("state") == "disabled", "reply text became editable"
    progress("inline reply: resume conversation")
    bubble.chat_button.invoke()
    root.update()
    assert windows.chat_window.winfo_viewable(), "chat button did not reopen the conversation"
    assert windows.chat_window.input.get("1.0", "end-1c") == draft, "existing draft was modified"
    assert memory.recent_turns(None) == saved_turns, "reading modified saved conversations"
    assert memory.counts() == saved_counts, "reading modified saved data"
    windows.chat_window._hide()
    root.update()
    assert desktop._chat_phase == "reply" and desktop._visible_speech().cget("text") == reply, "closing chat erased the answer"
    assert desktop._chat_expiry is None, "retained answer expires automatically"
    desktop._say("playful", "다음 기본 대사")
    assert desktop._visible_speech().cget("text") == reply, "ordinary dialogue erased the AI answer"
    windows.open_chat()
    root.update()
    assert reply in windows.chat_window.history.get("1.0", "end-1c"), "reopening chat lost conversation"
    assert windows.chat_window.input.get("1.0", "end-1c") == draft, "reopening chat lost draft"
    heartbeat = []
    root.after(1, lambda: heartbeat.append(True))
    root.after(25, root.quit)
    root.mainloop()
    assert heartbeat, "timer event loop stopped after inline input"


def run_packaged_smoke(app_factory, report_path):
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text('{"status":"running"}', encoding="utf-8")
    with report_path.with_suffix(".fault.log").open("w", encoding="utf-8") as fault_log:
        faulthandler.enable(file=fault_log, all_threads=True)
        faulthandler.dump_traceback_later(90, file=fault_log, exit=True)
        try:
            return _run_packaged_smoke(app_factory, report_path)
        finally:
            faulthandler.cancel_dump_traceback_later()
            faulthandler.disable()


def _run_packaged_smoke(app_factory, report_path):
    import tkinter as tk
    import app
    import desktop_compact as compact
    from settings import UserSettings, save_user_settings
    from workday import WorkdayState
    from app_brand import APP_VERSION

    report = {"version": APP_VERSION, "api_calls": 0, "isolated_profile": True, "checks": []}
    def progress(phase):
        report["phase"] = phase
        report["status"] = "running"
        Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    compact.enable_per_monitor_dpi_awareness()
    create_tk = tk.Tk
    try:
        for dpi in (96, 120, 144, 192):
            report["current_dpi"] = dpi
            progress("create desktop")
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
                        progress("preview navigation")
                        _exercise_preview_navigation(desktop)
                        progress("away clock")
                        _exercise_away_clock(desktop)
                        approval_resize = _exercise_approval_actions(desktop, progress)
                        _exercise_inline_reply(desktop, progress)
                        progress("settings and auxiliary windows")
                        windows.open_chat()
                        windows.open_settings()
                        from assistant_ai.config import MODELS
                        model_settings = windows.settings_window
                        assert tuple(model_settings.model_entry.cget("values")) == MODELS, "model choices missing"
                        configured_model = desktop._assistant_service.load_settings().model
                        model_settings.model.set("gpt-6-astra")
                        root.update()
                        assert "low" in model_settings.price.get(), "model reasoning description missing"
                        assert model_settings.save_button.winfo_viewable(), "model settings save button hidden"
                        assert desktop._assistant_service.load_settings().model == configured_model, "model preview saved itself"
                        model_settings.model.set(configured_model)
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
                        report["checks"].append({"dpi": dpi, "status": "passed", "approval_resize": approval_resize,
                                                 "flows": ["dice", "settings", "preview previous/next pixels and selection preservation", "visible cross-role Apply and Undo", "away clock and records", "small approval actions", "small image proposal actions", "three-line inline reply", "native repeated clicks and wheel", "scrollbar and keyboard reading", "explicit chat button", "conversation and draft preservation", "chat hide/reopen and retained answer", "AI settings", "model choices and unsaved preview", "memories", "image picker", "gallery", "backup", "weather", "offline status", "image cancel"]})
                    finally:
                        progress("close desktop")
                        for timer_id in root.tk.splitlist(root.tk.call("after", "info")):
                            root.tk.call("after", "cancel", timer_id)
                        desktop.quit()
        report["status"] = "passed"
        report["phase"] = "complete"
    except Exception:
        report["status"] = "failed"
        report["error"] = traceback.format_exc()
    Path(report_path).parent.mkdir(parents=True, exist_ok=True)
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["status"] == "passed" else 1
