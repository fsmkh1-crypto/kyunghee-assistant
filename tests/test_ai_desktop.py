"""Integration with the real gallery shell, using only isolated data and fake HTTP."""
from dataclasses import replace
from datetime import datetime
import json
import os
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

# app.py creates its log directory on import. Keep test runs out of real app data.
_DATA = tempfile.TemporaryDirectory(prefix="kyunghee-ai-ui-tests-")
os.environ["APPDATA"] = _DATA.name
os.environ.setdefault("PYSTRAY_BACKEND", "dummy")

from ai_desktop import chat_window_rect, local_chat_reply, place_chat_window, timer_context
from ai_dialogue import AIService, AssetToolCall
import asset_manager
from chat_asset_commands import AssetCommand, catalog_context
from image_sets import ImageSetStore
from desktop_gallery_final import FinalGalleryDesktopApp
from state import fresh_state


class ContextTests(unittest.TestCase):
    def test_chat_placement_prefers_adjacent_space_and_supports_negative_monitors(self):
        self.assertEqual(chat_window_rect((20, 40, 397, 500), (0, 0, 1280, 1024)),
                         (425, 40, 410, 500))
        self.assertEqual(chat_window_rect((859, 700, 397, 300), (0, 0, 1280, 1024)),
                         (441, 524, 410, 500))
        rect = chat_window_rect((-420, -80, 397, 400), (-1280, -200, 0, 824))
        self.assertEqual(rect, (-838, -80, 410, 500))
        x, y, width, height = rect
        self.assertEqual(f"{width}x{height}{x:+d}{y:+d}", "410x500-838-80")
        # Neither side fits here: keep the smaller overlap while staying inside.
        self.assertEqual(chat_window_rect((350, 40, 397, 500), (0, 0, 1024, 768)),
                         (0, 40, 410, 500))

    def test_negative_monitor_placement_uses_absolute_native_coordinates_on_Windows(self):
        window = MagicMock()
        window.winfo_id.return_value = 123
        with patch("ai_desktop.os.name", "nt"), patch("ai_desktop.ctypes.windll", create=True) as windll:
            windll.user32.GetAncestor.return_value = 456
            place_chat_window(window, -838, -80, 410, 500)
            windll.user32.GetAncestor.assert_called_once_with(123, 2)
            windll.user32.SetWindowPos.assert_called_once_with(456, 0, -838, -80, 410, 500, 0x0014)

    def test_snapshot_contains_only_requested_day_facts(self):
        state = fresh_state()
        state.daily.active_seconds = 3661
        state.session.continuous_seconds = 120
        result = timer_context(state, "wind_down", "warm", datetime(2026, 11, 6, 17, 15),
                               recent_break_minutes=5, api_key="DO-NOT-SEND", path="private")
        self.assertEqual(result["local_time"], "17:15")
        self.assertEqual(result["active_minutes"], 61)
        self.assertEqual(result["continuous_minutes"], 2)
        self.assertEqual(result["recent_break_minutes"], 5)
        self.assertEqual(result["workday_stage"], "wind_down")
        self.assertNotIn("api_key", result)
        self.assertNotIn("path", result)
        night = timer_context(state, "normal", "balanced", datetime(2026, 11, 6, 1, 0))
        self.assertEqual(night["time_of_day"], "late")

    def test_local_chat_uses_existing_personality_dialogue(self):
        with patch("ai_desktop.pick", return_value="기존 대사") as pick:
            self.assertEqual(local_chat_reply("조금 피곤해", "warm"), "기존 대사")
            pick.assert_called_once_with("break", personality="warm")


class BlockingClient:
    def __init__(self):
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = 0
        self.reply = SimpleNamespace(text="잘 왔어. 오늘도 옆에서 응원할게.", error_code="")

    def generate(self, _key, **_kwargs):
        self.calls += 1
        self.started.set()
        self.release.wait(2)
        return self.reply


class GalleryAITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import tkinter as tk
        try:
            root = tk.Tk()
            root.destroy()
        except tk.TclError:
            raise unittest.SkipTest("A display is needed for the real Tk gallery integration")

    def setUp(self):
        presentation = patch("desktop_compact.should_suppress_overlay_notifications", return_value=False)
        presentation.start()
        self.addCleanup(presentation.stop)
        self.client = BlockingClient()
        self.service = AIService(self.client, cooldown_seconds=0, chat_cooldown_seconds=0)
        with patch("ai_desktop.AIService", return_value=self.service), \
             patch("app.App._start_tray"), \
             patch("desktop_compact.CompactDesktopApp._start_global_hotkey"):
            self.app = FinalGalleryDesktopApp()
        self.app.root.update()

    def tearDown(self):
        self.client.release.set()
        self.app._ai_closed = True
        self.service.close()
        for pending in self.app.root.tk.call("after", "info"):
            # Tcl cancellation leaves each child widget's registered command
            # for that widget to delete during destruction.
            self.app.root.tk.call("after", "cancel", pending)
        self.app.root.destroy()
        if self.service._worker:
            self.service._worker.join(timeout=1)

    def enable(self):
        self.app.ai_credentials.configure_key("test-key-no-network", False)
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=True,
                                          ai_remember_key=False))

    def flush(self):
        deadline = time.monotonic() + 1
        while self.service._in_flight is not None and time.monotonic() < deadline:
            self.app._ai_poll()
            self.app.root.update_idletasks()
            time.sleep(.002)

    def send(self, text="안녕"):
        self.app._chat_entry.insert(0, text)
        self.app._send_chat()

    def preserve_selection_files(self):
        paths = (Path(self.app.MANUAL_OVERRIDE_FILE), Path(__import__("app").SETTINGS_FILE))
        saved = {path: path.read_bytes() if path.is_file() else None for path in paths}
        def restore():
            for path, content in saved.items():
                self.app._restore_chat_selection_file(path, content)
        self.addCleanup(restore)
        return saved

    def tool_reply(self, command):
        self.client.reply = SimpleNamespace(text="", error_code="", tool_calls=(AssetToolCall("call_test", command),))

    def complete_tool(self, text, command):
        self.tool_reply(command)
        self.send(text)
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()

    def test_disabled_chat_immediately_uses_local_reply_without_touching_timer(self):
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=False))
        self.app._open_chat()
        before = (self.app.state.daily.active_seconds, self.app.state.session.continuous_seconds,
                  self.app.state.session.is_away)
        self.app._chat_entry.insert(0, "고마워")
        self.app._send_chat()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")
        self.assertEqual(self.client.calls, 0)
        self.assertEqual(before, (self.app.state.daily.active_seconds,
                         self.app.state.session.continuous_seconds, self.app.state.session.is_away))

    def test_delayed_ai_does_not_block_tick_and_stale_return_is_discarded(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "안녕")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 대기 중")
        engine = self.app.engine
        current = engine.last_mono
        engine.clock = lambda: current + 2
        engine.wall = lambda: engine.last_wall + 2
        engine.idle_provider = lambda: (0.0, 1)
        active_before = self.app.state.daily.active_seconds
        self.app._tick_safe()
        self.assertGreater(self.app.state.daily.active_seconds, active_before)
        self.app.toggle_manual_away()
        away_line = self.app.speech.cget("text")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), away_line)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 안내")
        self.assertIsNone(self.app._chat_pending)

    def test_AI_send_waits_without_local_dialogue_or_changing_main_speech(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.app.last_dialogue_at = time.monotonic() - 65
        self.app.last_work_mode = self.app._current_workday_state().mode
        with patch("ai_desktop.local_chat_reply") as local_reply, \
             patch.object(self.service, "note_local", wraps=self.service.note_local) as note_local:
            self.send()
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            self.assertEqual(self.app._chat_messages[-1][0], "승아 · 대기 중")
            self.assertIn("기다리고", self.app._chat_ai_note)
            local_reply.assert_not_called()
            note_local.assert_not_called()
            with patch.object(self.app, "_say") as say:
                self.app._update_dialogue()
                say.assert_not_called()
            self.assertEqual(self.app.speech.cget("text"), before)

    def test_transport_error_only_then_shows_local_fallback(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.client.reply = SimpleNamespace(text="", error_code="connection_error")
        with patch("ai_desktop.local_chat_reply", return_value="연결이 없어도 잠깐 쉬어가자.") as local_reply, \
             patch.object(self.service, "note_local", wraps=self.service.note_local) as note_local:
            self.send("조금 피곤해")
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            local_reply.assert_not_called()
            note_local.assert_not_called()
            self.client.release.set()
            self.flush()
            local_reply.assert_called_once_with("조금 피곤해", self.app.preferences.personality)
            note_local.assert_called_once_with("연결이 없어도 잠깐 쉬어가자.")
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1], ("승아 · 로컬", "연결이 없어도 잠깐 쉬어가자."))
        self.assertEqual(self.app.speech.cget("text"), "연결이 없어도 잠깐 쉬어가자.")

    def test_UI_deadline_falls_back_when_backend_drops_response_and_ignores_late_reply(self):
        self.enable()
        self.app._open_chat()
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        pending = self.app._chat_pending
        with patch("ai_desktop.time", SimpleNamespace(monotonic=lambda: pending.deadline + .01)), \
             patch.object(self.service, "poll", return_value=[]), \
             patch("ai_desktop.local_chat_reply", return_value="조금 늦네. 천천히 쉬어가자."):
            self.app._ai_poll()
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")
        self.assertIn("초과", self.app._chat_ai_note)
        fallback = self.app.speech.cget("text")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), fallback)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")

    def test_repeated_send_retains_first_request_and_new_input(self):
        self.enable()
        self.app._open_chat()
        self.send("처음 말")
        self.assertTrue(self.client.started.wait(.5))
        pending = self.app._chat_pending
        generation = self.service._generation
        before = self.app.speech.cget("text")
        self.send("다음 말")
        self.assertIs(self.app._chat_pending, pending)
        self.assertEqual(self.service._generation, generation)
        self.assertEqual(self.app._chat_entry.get(), "다음 말")
        self.assertEqual(len(self.app._chat_messages), 2)
        self.assertEqual(self.app.speech.cget("text"), before)
        self.assertEqual(self.client.calls, 1)
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")

    def test_busy_or_cooldown_keeps_input_and_never_invents_local_response(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        with patch.object(self.service, "request", return_value=False), \
             patch("ai_desktop.local_chat_reply") as local_reply, \
             patch.object(self.service, "note_local") as note_local:
            self.send("잠시 대화할까")
        local_reply.assert_not_called()
        note_local.assert_not_called()
        self.assertEqual(self.app._chat_entry.get(), "잠시 대화할까")
        self.assertEqual(self.app.speech.cget("text"), before)
        self.assertFalse(self.app._chat_messages)
        self.assertIsNone(self.app._chat_pending)
        self.assertIn("잠시 후", self.app._chat_ai_note)

    def test_daily_close_also_waits_and_only_uses_fallback_after_error(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.client.reply = SimpleNamespace(text="", error_code="timeout")
        with patch("ai_desktop.pick", return_value="오늘은 여기까지. 편하게 마무리하자.") as pick:
            self.app._daily_close()
            self.assertTrue(self.client.started.wait(.5))
            self.assertEqual(self.app.speech.cget("text"), before)
            pick.assert_not_called()
            self.client.release.set()
            self.flush()
            pick.assert_called_once_with("leave", personality=self.app.preferences.personality)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 로컬")

    def test_clear_chat_discards_pending_and_late_result_without_speech_change(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        self.app._clear_chat()
        self.assertIsNone(self.app._chat_pending)
        self.client.release.set()
        self.flush()
        self.assertFalse(self.app._chat_messages)
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_personality_change_cancels_pending_without_fallback(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        personality = "strict" if self.app.preferences.personality != "strict" else "warm"
        self.app.apply_preferences(replace(self.app.preferences, personality=personality))
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 안내")
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_explicit_chat_completes_even_when_overlay_notifications_are_suppressed(self):
        self.enable()
        self.app._open_chat()
        before = self.app.speech.cget("text")
        self.send()
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        with patch.object(self.app, "_break_notifications_suppressed", return_value=True):
            self.flush()
        self.assertIsNone(self.app._chat_pending)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_chat_is_always_topmost_on_create_refresh_reopen_and_preferences(self):
        self.app.apply_preferences(replace(self.app.preferences, always_on_top=False))
        # Chat must also handle an old false preference still held in memory;
        # applying current preferences normalizes the timer's setting to true.
        self.app.preferences = replace(self.app.preferences, always_on_top=False)
        original_attributes = __import__("tkinter").Toplevel.attributes
        calls = []
        def attributes(window, *args):
            calls.append((window, args))
            return original_attributes(window, *args)
        with patch("ai_desktop.tk.Toplevel.attributes", autospec=True, side_effect=attributes):
            self.app._open_chat()
            window = self.app._chat_window
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            self.app._refresh_chat()
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            window.withdraw()
            self.app._open_chat()
            self.assertIn((window, ("-topmost", True)), calls)
            calls.clear()
            self.app.apply_preferences(replace(self.app.preferences, always_on_top=False))
            self.assertIn((window, ("-topmost", True)), calls)
            self.assertTrue(self.app.preferences.always_on_top)
        self.assertEqual(window.title(), "승아와 대화")

    def test_startup_opens_chat_and_bubble_only_focuses_it_without_dialogue_or_API(self):
        self.assertIsNotNone(self.app._chat_window)
        self.assertFalse(hasattr(self.app, "chat_control"))
        window = self.app._chat_window
        window.withdraw()
        before = self.app.speech.cget("text")
        with patch.object(self.app, "_request_ai") as request, \
             patch.object(self.service, "note_local") as note_local:
            self.app.speech.event_generate("<Button-1>", x=5, y=5)
            self.app.root.update()
        self.assertIs(self.app._chat_window, window)
        self.assertEqual(window.state(), "normal")
        self.assertEqual(self.app.speech.cget("text"), before)
        request.assert_not_called()
        note_local.assert_not_called()

    def test_character_click_focuses_chat_and_drag_never_cycles_or_opens_stats(self):
        before = self.app.speech.cget("text")
        origin = SimpleNamespace(x_root=100, y_root=100)
        moved = SimpleNamespace(x_root=115, y_root=100)
        with patch.object(self.app, "_open_chat") as open_chat, \
             patch.object(self.app, "show_stats") as stats, \
             patch.object(self.app, "_pick_dialogue") as dialogue:
            self.app._start_character_drag(origin)
            self.app._stop_character_drag(origin)
            open_chat.assert_called_once()
            open_chat.reset_mock()
            self.app._start_character_drag(origin)
            self.app._drag_character(moved)
            self.app._stop_character_drag(moved)
            open_chat.assert_not_called()
            stats.assert_not_called()
            dialogue.assert_not_called()
        self.assertEqual(self.app.speech.cget("text"), before)

    def test_chat_opens_left_of_main_window_at_right_work_area_edge_without_overlap(self):
        left, top, right, bottom = self.app._work_areas()[0]
        width, height = self.app.root.winfo_width(), self.app.root.winfo_height()
        self.app._set_window_rect(right - width - 12, top + 20, width, height)
        self.app.root.update_idletasks()
        self.app._chat_window.destroy()
        self.app._chat_window = None
        self.app._open_chat()
        self.app.root.update_idletasks()
        chat = self.app._chat_window
        self.assertLessEqual(chat.winfo_x() + chat.winfo_width(), self.app.root.winfo_x() - 8)
        self.assertGreaterEqual(chat.winfo_x(), left)
        self.assertGreaterEqual(chat.winfo_y(), top)
        self.assertLessEqual(chat.winfo_y() + chat.winfo_height(), bottom)

    def test_tool_set_persists_and_renders_now_and_after_restart_without_deleting_imports(self):
        self.preserve_selection_files()
        self.enable()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        store = ImageSetStore(Path(temporary.name) / "image-sets")
        source = asset_manager.variant_asset("default", 1, asset_manager.ASSET_DIR)
        store.import_files("default", [source])
        imported = tuple(store.list_images("default"))
        imported_bytes = {path: path.read_bytes() for path in imported}
        manifest_before = store.manifest_path.read_bytes()
        self.app._image_set_store = store
        photo = self.app.character_photo
        self.complete_tool("3번 세트로 바꿔줘", AssetCommand("set", number=3))
        self.assertEqual(self.app.preferences.builtin_image_set, "03")
        self.assertEqual(self.app.builtin_image_set_var.get(), "03")
        self.assertEqual(self.app._manual_override_path("default").name, "default_03.png")
        self.assertIsNot(self.app.character_photo, photo)
        self.assertEqual(store.manifest_path.read_bytes(), manifest_before)
        self.assertEqual({path: path.read_bytes() for path in imported}, imported_bytes)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 설정")
        self.assertIn("03번", self.app._chat_messages[-1][1])
        self.assertTrue(self.service._chat)
        self.assertIn("03번", self.service._chat[-1][1])
        settings = json.loads(__import__("app").SETTINGS_FILE.read_text())
        self.assertEqual(settings["builtin_image_set"], "03")
        self.assertEqual(json.loads(Path(self.app.MANUAL_OVERRIDE_FILE).read_text())["default"],
                         "builtin:default/default_03.png")
        self.app._ai_closed = True
        self.service.close()
        for pending in self.app.root.tk.call("after", "info"):
            self.app.root.tk.call("after", "cancel", pending)
        self.app.root.destroy()
        if self.service._worker:
            self.service._worker.join(timeout=1)
        restarted_service = AIService(BlockingClient())
        with patch("ai_desktop.AIService", return_value=restarted_service), \
             patch("app.App._start_tray"), \
             patch("desktop_compact.CompactDesktopApp._start_global_hotkey"):
            self.app = FinalGalleryDesktopApp()
        self.service = restarted_service
        self.app.root.update_idletasks()
        self.assertEqual(self.app.preferences.builtin_image_set, "03")
        self.assertEqual(self.app._custom_image("default")[0].name, "default_03.png")
        self.assertEqual(self.app.character_role, "default")
        self.assertGreater(self.app.character_photo.width(), 0)

    def test_plaintext_success_claim_without_tool_keeps_settings_and_shows_truthful_reply(self):
        self.enable()
        preferences = self.app.preferences
        manual = dict(self.app._manual_asset_overrides)
        self.client.reply = SimpleNamespace(text="3번 이미지로 바꿨어. 설정도 저장했어.", error_code="")
        self.send("3번 세트로 바꿔줘")
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.preferences, preferences)
        self.assertEqual(self.app._manual_asset_overrides, manual)
        self.assertIn("설정은 그대로", self.app._chat_messages[-1][1])
        self.assertNotIn("저장했어", self.app._chat_messages[-1][1])

    def test_role_file_tool_changes_only_current_slot_and_preserves_global_and_other_manuals(self):
        self.preserve_selection_files()
        self.enable()
        previous_set = self.app.preferences.builtin_image_set
        other = "builtin:away/away_01.png"
        self.app._manual_asset_overrides["away"] = other
        catalog, paths = self.app._chat_asset_catalog()
        choice = next(item for item in catalog.images if item.filename == "rest_03.png")
        self.complete_tool("3번 휴식 이미지로 바꿔줘", AssetCommand("file", asset_id=choice.asset_id))
        self.assertEqual(self.app._manual_override_path("default"), paths[choice.asset_id])
        self.assertEqual(self.app._manual_asset_overrides["away"], other)
        self.assertEqual(self.app.preferences.builtin_image_set, previous_set)
        self.assertEqual(self.app.character_role, "default")
        self.assertIn("rest_03.png", self.app._chat_messages[-1][1])

    def test_exact_catalog_filename_tool_is_resolved_and_rendered(self):
        self.preserve_selection_files()
        self.enable()
        catalog, _paths = self.app._chat_asset_catalog()
        choice = next(item for item in catalog.images if item.filename == "rest_03.png")
        self.complete_tool("rest_03.png로 바꿔줘", AssetCommand("file", asset_id=choice.asset_id))
        self.assertEqual(self.app._manual_override_path("default").name, "rest_03.png")
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 설정")

    def test_ambiguous_or_different_user_number_cannot_apply_model_proposal(self):
        self.preserve_selection_files()
        self.enable()
        preferences = self.app.preferences
        manual = dict(self.app._manual_asset_overrides)
        self.complete_tool("이미지 바꿔줘", AssetCommand("set", number=3))
        self.assertEqual(self.app.preferences, preferences)
        self.assertEqual(self.app._manual_asset_overrides, manual)
        self.assertIn("바꾸지 않았어", self.app._chat_messages[-1][1])

    def test_nonexistent_or_external_image_selection_never_writes_settings(self):
        before = self.app.preferences
        with patch.object(self.app, "_save_manual_overrides") as save:
            ok, _message = self.app._select_chat_asset(number=99)
            self.assertFalse(ok)
            ok, _message = self.app._select_chat_asset(path=Path("/untrusted/image.png"))
            self.assertFalse(ok)
            save.assert_not_called()
        self.assertEqual(self.app.preferences, before)

    def test_settings_save_failure_rolls_back_manual_file_preferences_and_render(self):
        before_files = self.preserve_selection_files()
        before_preferences = self.app.preferences
        before_manual = dict(self.app._manual_asset_overrides)
        before_photo = self.app.character_photo
        with patch("app.save_user_settings", side_effect=OSError("private file path")):
            ok, message = self.app._select_chat_asset(number=3)
        self.assertFalse(ok)
        self.assertNotIn("바꿨어", message)
        self.assertNotIn("private", message)
        self.assertEqual(self.app.preferences, before_preferences)
        self.assertEqual(self.app._manual_asset_overrides, before_manual)
        self.assertIs(self.app.character_photo, before_photo)
        self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in before_files}, before_files)

    def test_render_failure_rolls_back_both_selection_files(self):
        before_files = self.preserve_selection_files()
        before_photo = self.app.character_photo
        with patch.object(self.app, "_set_character"):
            ok, _message = self.app._select_chat_asset(number=3)
        self.assertFalse(ok)
        self.assertIs(self.app.character_photo, before_photo)
        self.assertEqual({path: path.read_bytes() if path.is_file() else None for path in before_files}, before_files)

    def test_new_manual_gallery_choice_invalidates_blocked_tool_proposal(self):
        self.preserve_selection_files()
        self.enable()
        self.tool_reply(AssetCommand("set", number=3))
        self.send("3번 세트로 바꿔줘")
        self.assertTrue(self.client.started.wait(.5))
        chosen = asset_manager.variant_asset("default", 2, asset_manager.ASSET_DIR)
        self.app._apply_gallery_path("default", chosen)
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._manual_override_path("default"), chosen)
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 안내")

    def test_clear_or_expired_tool_response_cannot_change_selection(self):
        self.preserve_selection_files()
        self.enable()
        before = self.app.preferences
        manual = dict(self.app._manual_asset_overrides)
        self.tool_reply(AssetCommand("set", number=3))
        self.send("3번 세트로 바꿔줘")
        self.assertTrue(self.client.started.wait(.5))
        self.app._clear_chat()
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app.preferences, before)
        self.assertEqual(self.app._manual_asset_overrides, manual)
        self.assertFalse(self.app._chat_messages)

    def test_status_tool_reads_fresh_actual_state_without_mutation_or_main_numbers(self):
        self.enable()
        before = self.app.preferences
        speech = self.app.speech.cget("text")
        manual = dict(self.app._manual_asset_overrides)
        self.tool_reply(AssetCommand("status"))
        self.send("오늘 얼마나 일했어")
        self.assertTrue(self.client.started.wait(.5))
        self.app.state.daily.active_seconds = 97
        self.app.state.daily.away_seconds = 12
        self.app.state.session.continuous_seconds = 19
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 타이머")
        message = self.app._chat_messages[-1][1]
        self.assertIn("1분 37초", message)
        self.assertIn("12초", message)
        self.assertIn("19초", message)
        self.assertEqual(self.app.preferences, before)
        self.assertEqual(self.app._manual_asset_overrides, manual)
        self.assertEqual(self.app.speech.cget("text"), speech)

    def test_offline_status_query_reports_zero_and_seconds_without_API_or_random_reply(self):
        self.app.apply_preferences(replace(self.app.preferences, ai_enabled=False))
        self.app.state.daily.active_seconds = 0
        self.app.state.daily.away_seconds = 7
        self.app.state.session.continuous_seconds = 3
        speech = self.app.speech.cget("text")
        with patch("ai_desktop.local_chat_reply") as random_reply:
            self.send("오늘 얼마나 일했어")
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 타이머")
        self.assertIn("0초", self.app._chat_messages[-1][1])
        self.assertIn("7초", self.app._chat_messages[-1][1])
        random_reply.assert_not_called()
        self.assertEqual(self.client.calls, 0)
        self.assertEqual(self.app.speech.cget("text"), speech)

    def test_plaintext_API_timer_answer_is_replaced_with_actual_records(self):
        self.enable()
        self.app.state.daily.active_seconds = 21
        self.client.reply = SimpleNamespace(text="오늘은 999시간 일했어.", error_code="")
        self.send("오늘 얼마나 일했어")
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()
        self.assertIn("21초", self.app._chat_messages[-1][1])
        self.assertNotIn("999", self.app._chat_messages[-1][1])
        self.assertFalse(self.service._chat)

    def test_failed_API_timer_query_still_reads_actual_records_without_random_fallback(self):
        self.enable()
        self.client.reply = SimpleNamespace(text="", error_code="timeout")
        speech = self.app.speech.cget("text")
        self.send("사용 시간 알려줘")
        self.assertTrue(self.client.started.wait(.5))
        self.app.state.daily.active_seconds = 42
        self.client.release.set()
        with patch("ai_desktop.local_chat_reply") as random_reply:
            self.flush()
        random_reply.assert_not_called()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · 타이머")
        self.assertIn("42초", self.app._chat_messages[-1][1])
        self.assertEqual(self.app.speech.cget("text"), speech)

    def test_temporarily_missing_builtin_manual_ref_is_preserved_and_restored(self):
        self.preserve_selection_files()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        folder = root / "default"
        folder.mkdir()
        content = asset_manager.variant_asset("default", 1, asset_manager.ASSET_DIR).read_bytes()
        fallback = folder / "main_kyunghee.png"
        fallback.write_bytes(content)
        ref = "builtin:default/default_17.png"
        self.app._manual_asset_overrides["default"] = ref
        self.app._save_manual_overrides()
        before = Path(self.app.MANUAL_OVERRIDE_FILE).read_bytes()
        with patch("asset_manager.ASSET_DIR", root), \
             patch.object(self.app, "_resolve_builtin_asset", return_value=fallback):
            self.assertIsNone(self.app._manual_override_path("default"))
            self.app.character_role = None
            self.app._set_character("default")
            self.assertEqual(self.app.character_role, "default")
            self.assertEqual(self.app._manual_asset_overrides["default"], ref)
            self.assertEqual(Path(self.app.MANUAL_OVERRIDE_FILE).read_bytes(), before)
            restored = folder / "default_17.png"
            restored.write_bytes(content)
            self.assertEqual(self.app._manual_override_path("default"), restored)
        self.assertEqual(Path(self.app.MANUAL_OVERRIDE_FILE).read_bytes(), before)

    def test_catalog_metadata_contains_opaque_ids_and_no_local_paths_or_custom_names(self):
        catalog, paths = self.app._chat_asset_catalog()
        payload = json.dumps(catalog_context(catalog))
        self.assertTrue(catalog.images)
        self.assertEqual(set(paths), {choice.asset_id for choice in catalog.images})
        self.assertNotIn(str(asset_manager.ASSET_DIR), payload)
        self.assertNotIn(_DATA.name, payload)

    def test_custom_image_acknowledgement_keeps_private_filename_out_of_API_memory(self):
        self.preserve_selection_files()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        folder = Path(temporary.name) / "roles" / "default"
        folder.mkdir(parents=True)
        image = folder / "private-customer-project.png"
        image.write_bytes(asset_manager.variant_asset("default", 1, asset_manager.ASSET_DIR).read_bytes())
        with patch("desktop_compact.USER_IMAGE_SET_DIR", Path(temporary.name)):
            catalog, paths = self.app._chat_asset_catalog()
            choice = next(choice for choice in catalog.images if paths[choice.asset_id] == image)
            self.assertEqual(choice.filename, "")
            self.assertNotIn(image.name, json.dumps(catalog_context(catalog)))
            ok, acknowledgement = self.app._select_chat_asset(path=image)
            self.assertTrue(ok)
            self.assertNotIn(image.name, acknowledgement)
            self.assertNotIn(str(image.parent), acknowledgement)
            self.assertEqual(self.app._manual_override_path("default"), image)

    def test_ZIP_import_reports_automatic_number_for_complete_role_only_pack(self):
        self.assertIn("번호 없이", self.app._pack_status.cget("text"))
        result = SimpleNamespace(sets=("06",), added=10, identical=0, auto_assigned=("06",), reused=())
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-role-only.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("06번을 자동 배정", message)
        self.assertIn("10장 추가", message)
        self.assertNotIn("기존 06번", message)

    def test_ZIP_import_reports_reused_existing_number_without_claiming_new_images(self):
        result = SimpleNamespace(sets=("03",), added=0, identical=10, auto_assigned=(), reused=("03",))
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-repeat.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("기존 03번을 그대로 사용", message)
        self.assertIn("0장 추가", message)
        self.assertIn("동일 파일 10장 유지", message)
        self.assertNotIn("자동 배정", message)
        self.assertNotIn("앱을 다시 열면", message)

    def test_ZIP_import_reports_merged_incoming_groups_without_claiming_installed_number(self):
        result = SimpleNamespace(sets=("22",), added=10, identical=0, auto_assigned=(), reused=("22",))
        with patch("ai_desktop.filedialog.askopenfilename", return_value="fixture-merged.zip"), \
             patch("ai_desktop.import_numbered_pack", return_value=result):
            self.app._import_asset_pack()
        message = self.app._pack_status.cget("text")
        self.assertIn("동일한 내용의 세트는 22번으로 합쳤습니다", message)
        self.assertIn("10장 추가", message)
        self.assertNotIn("기존 22번", message)
        self.assertNotIn("자동 배정", message)

    def test_current_ai_reply_appears_and_key_never_enters_settings(self):
        self.enable()
        self.app._open_chat()
        self.app._chat_entry.insert(0, "다녀왔어")
        self.app._send_chat()
        self.assertTrue(self.client.started.wait(.5))
        self.client.release.set()
        self.flush()
        self.assertEqual(self.app._chat_messages[-1][0], "승아 · AI")
        self.assertEqual(self.app.speech.cget("text"), "잘 왔어. 오늘도 옆에서 응원할게.")
        from app import SETTINGS_FILE
        saved = SETTINGS_FILE.read_text(encoding="utf-8")
        self.assertNotIn("test-key-no-network", saved)
        self.assertNotIn("api_key", saved)
        self.app._save_settings()
        self.assertTrue(self.app.preferences.ai_enabled)
        self.app._clear_chat()
        self.assertFalse(self.app._chat_messages)

    def test_clearing_key_and_turning_off_stop_runtime_even_when_settings_write_fails(self):
        self.enable()
        self.assertTrue(self.service._enabled)
        self.app.ai_credentials.clear()
        with patch("app.save_user_settings", side_effect=OSError("read-only settings")):
            with self.assertRaises(OSError):
                self.app._apply_ai_settings(True, False, "")
        self.assertFalse(self.service._enabled)
        self.assertEqual(self.service._api_key, "")
        self.enable()
        with patch("app.save_user_settings", side_effect=OSError("read-only settings")):
            with self.assertRaises(OSError):
                self.app._apply_ai_settings(False, False, self.app.ai_credentials.api_key)
        self.assertFalse(self.service._enabled)
        self.assertFalse(self.app.preferences.ai_enabled)


if __name__ == "__main__":
    unittest.main()
