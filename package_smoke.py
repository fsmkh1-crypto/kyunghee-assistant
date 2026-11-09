"""Exercise the packaged GUI without network requests or a real user profile."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch


def run_packaged_smoke(app_factory, report_path):
    import tkinter as tk
    import app
    import desktop_compact as compact
    from settings import UserSettings, save_user_settings
    from workday import WorkdayState
    from app_brand import APP_VERSION

    report = {"version": APP_VERSION, "api_calls": 0, "isolated_profile": True, "checks": []}
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
                    return root

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
                        report["checks"].append({"dpi": dpi, "status": "passed",
                                                 "flows": ["dice", "settings", "away", "chat", "AI settings", "memories", "image picker", "gallery", "backup", "weather", "offline status", "image cancel"]})
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
