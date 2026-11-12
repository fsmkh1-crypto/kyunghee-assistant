from __future__ import annotations

from dataclasses import replace
from datetime import date
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


@unittest.skipUnless(os.name == "nt" or bool(os.environ.get("DISPLAY")), "Tk display required")
class SettingsAndMemoryWindowTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from assistant_ai.config import AISettings
        from assistant_ai.memory import MemoryStore
        from assistant_ai.ui import AssistantWindows
        from assistant_ai.ui_settings import _SettingsWindow
        from assistant_ai.ui_memory import _MemoryWindow

        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = tk.Tk()
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        store = MemoryStore(Path(self.temp.name) / "memory.sqlite3")
        store.set_enabled(True)
        self.current = AISettings(memory_enabled=True)
        self.has_key = False
        self.service = SimpleNamespace(
            load_settings=lambda: self.current,
            has_key=lambda: self.has_key,
            supports_key_persistence=True,
            persistent_key=False,
            settings_issue="",
            memory=store,
            history_counts=lambda: {**store.counts(), "session_turns": 0},
            invalidate_context=Mock(),
            delete_memory=store.delete_memory,
            clear_memories=store.clear_memories,
            connection_test=Mock(return_value="시험 성공"),
            ledger=SimpleNamespace(summary=lambda *_: SimpleNamespace(
                requests=0, total_tokens=0, estimated_cost_usd=0.0,
                reserved_cost_usd=0.0, remaining_budget_usd=None, unconfirmed_requests=0,
            )),
        )

        def save(settings, *, new_key=None, remove_key=False):
            settings.validate()
            self.current = settings
            store.set_enabled(settings.memory_enabled)
            store.set_history_enabled(settings.conversation_storage_enabled)
            self.has_key = bool(new_key) or self.has_key and not remove_key

        self.service.save_settings = Mock(side_effect=save)
        self.owner = AssistantWindows(self.root, self.service, context=lambda: {}, dispatch=lambda *_: None)
        self.owner.settings_changed = Mock()
        self.owner.run_background = lambda operation, done: done(operation(), None)
        self.settings = _SettingsWindow(self.owner)
        self.settings.reload()
        self.memory = _MemoryWindow(self.owner)
        self.memory.refresh()

    def test_settings_hide_keeps_draft_and_discard_reloads(self):
        self.settings.model.set("custom-model")
        self.assertTrue(self.settings.dirty)
        self.settings._hide()
        self.settings.show()
        self.assertEqual(self.settings.model.get(), "custom-model")
        self.assertTrue(self.settings.dirty)
        self.settings.reload()
        self.assertEqual(self.settings.model.get(), self.current.model)
        self.assertFalse(self.settings.dirty)

    def test_settings_save_separates_history_memory_and_preserves_event_choices(self):
        self.settings.history.set(True)
        self.settings.memory.set(False)
        self.settings.web_search.set(False)
        self.settings.proactive.set(True)
        self.settings.quiet.set(True)
        self.settings.event_vars["away"].set(False)
        self.settings.reading_size.set("16")
        self.assertTrue(self.settings._save())
        self.assertTrue(self.current.conversation_storage_enabled)
        self.assertFalse(self.current.memory_enabled)
        self.assertFalse(self.current.web_search_enabled)
        self.assertNotIn("away", self.current.proactive_events)
        self.assertEqual(self.current.proactive_quiet_until, date.today().isoformat())
        self.assertEqual(self.current.reading_text_size, 16)
        self.assertFalse(self.settings.dirty)
        self.owner.settings_changed.assert_called_once()

    def test_invalid_settings_leave_draft_and_saved_settings_unchanged(self):
        original = self.current
        self.settings.reading_size.set("99")
        self.assertFalse(self.settings._save())
        self.assertEqual(self.current, original)
        self.assertEqual(self.settings.reading_size.get(), "99")
        self.assertTrue(self.settings.dirty)
        self.service.save_settings.assert_not_called()

    def test_connection_test_uses_draft_without_saving(self):
        self.settings.key.set("sk-test-only")
        self.settings.model.set("custom-model")
        self.assertIn("유료", self.settings.test_button.cget("text"))
        self.settings._test_connection()
        arguments = self.service.connection_test.call_args.kwargs
        self.assertEqual(arguments["new_key"], "sk-test-only")
        self.assertEqual(arguments["model"], "custom-model")
        self.service.save_settings.assert_not_called()
        self.assertIsNone(self.settings._test_cancel)
        self.assertEqual(self.settings.status.get(), "시험 성공")

    def test_clean_settings_follow_external_changes_but_dirty_draft_survives(self):
        self.current = replace(self.current, weather_location="대전시")
        self.settings.show()
        self.assertEqual(self.settings.weather_location.get(), "대전시")
        self.settings.weather_location.set("서울시")
        self.current = replace(self.current, weather_location="부산시")
        self.settings.show()
        self.assertEqual(self.settings.weather_location.get(), "서울시")
        self.assertTrue(self.settings.dirty)

    def test_proactive_controls_are_visible_without_opening_advanced(self):
        for dpi in (96, 144, 192):
            with self.subTest(dpi=dpi):
                self.root.tk.call("tk", "scaling", dpi / 72)
                self.settings.show()
                self.settings.canvas.yview_moveto(0)
                self.root.update()
                self.assertFalse(self.settings._advanced_open)
                self.assertFalse(self.settings.advanced.winfo_ismapped())
                for widget in (self.settings.proactive_check, self.settings.proactive_interval_entry, self.settings.chatter_check):
                    self.assertTrue(widget.winfo_viewable())
                    top = widget.winfo_rooty() - self.settings.canvas.winfo_rooty()
                    left = widget.winfo_rootx() - self.settings.canvas.winfo_rootx()
                    self.assertGreaterEqual(top, 0)
                    self.assertGreaterEqual(left, 0)
                    self.assertLessEqual(top + widget.winfo_height(), self.settings.canvas.winfo_height())
                    self.assertLessEqual(left + widget.winfo_width(), self.settings.canvas.winfo_width())
                self.assertEqual(float(self.settings.proactive_interval_entry.cget("from")), 1)
                self.assertEqual(float(self.settings.proactive_interval_entry.cget("to")), 120)
                self.assertEqual(float(self.settings.proactive_interval_entry.cget("increment")), 1)

    def test_proactive_one_minute_save_reopen_and_toggle_preserve_other_settings(self):
        self.current = replace(self.current, enabled=True, weather_location="대전시",
                               proactive_interval_minutes=20, daily_request_limit=40, daily_token_limit=9000,
                               daily_budget_usd=1.25, proactive_events=("return", "periodic"))
        self.settings.reload()
        original = self.current
        self.assertEqual(self.settings.proactive_interval.get(), "20")
        self.assertIn("간격 20분", self.settings.proactive_state.get())
        self.settings.proactive_check.invoke()
        self.settings.proactive_interval.set("1")
        self.assertTrue(self.settings._save())
        self.assertEqual(self.current, replace(original, proactive_enabled=True, proactive_interval_minutes=1))
        self.settings._hide()
        self.settings.show()
        self.assertTrue(self.settings.proactive.get())
        self.assertEqual(self.settings.proactive_interval.get(), "1")
        self.settings.proactive_check.invoke()
        self.assertTrue(self.settings._save())
        self.assertEqual(self.current, replace(original, proactive_interval_minutes=1))

    def test_proactive_existing_interval_and_unsaved_draft_are_kept(self):
        self.current = replace(self.current, proactive_enabled=True, proactive_interval_minutes=20)
        self.settings.reload()
        self.settings.show()
        self.assertEqual(self.settings.proactive_interval.get(), "20")
        self.settings.proactive_interval.set("1")
        self.settings.proactive.set(False)
        self.settings._hide()
        self.settings.show()
        self.assertEqual(self.settings.proactive_interval.get(), "1")
        self.assertFalse(self.settings.proactive.get())
        self.assertTrue(self.settings.dirty)
        self.assertEqual(self.current.proactive_interval_minutes, 20)
        self.assertTrue(self.current.proactive_enabled)
        self.assertIn("간격 20분", self.settings.proactive_state.get())
        self.settings.reload()
        self.assertEqual(self.settings.proactive_interval.get(), "20")
        self.assertTrue(self.settings.proactive.get())

    def test_proactive_interval_out_of_range_keeps_saved_settings_and_draft(self):
        original = self.current
        for interval in ("0", "121"):
            self.settings.proactive_interval.set(interval)
            self.assertFalse(self.settings._save())
            self.assertEqual(self.current, original)
            self.assertEqual(self.settings.proactive_interval.get(), interval)
        self.service.save_settings.assert_not_called()

    def test_proactive_status_reports_saved_prerequisites_and_runtime_without_saving(self):
        self.current = replace(self.current, enabled=True, proactive_enabled=True, proactive_interval_minutes=20)
        self.settings.reload()
        self.assertIn("API 키 등록", self.settings.proactive_state.get())
        self.has_key = True
        self.current = replace(self.current, proactive_quiet_until=date.today().isoformat())
        self.settings.reload()
        self.assertIn("오늘은 쉬는 중", self.settings.proactive_state.get())
        self.owner.proactive_status = Mock(return_value={"reason": "미전송 초안이 있어 기다리는 중이에요.",
            "next_in_seconds": 30, "last_message": "최근 요청은 실패했어요. 사용량이 있을 수 있어요."})
        self.settings.proactive_interval.set("1")
        self.settings.proactive_refresh.invoke()
        self.assertIn("조회", self.settings.proactive_runtime.get())
        self.assertIn("미전송 초안", self.settings.proactive_runtime.get())
        self.assertIn("30초", self.settings.proactive_runtime.get())
        self.assertIn("최근 요청은 실패", self.settings.proactive_runtime.get())
        self.assertEqual(self.settings.proactive_interval.get(), "1")
        self.assertTrue(self.settings.dirty)
        self.service.save_settings.assert_not_called()
        self.service.connection_test.assert_not_called()

    def test_settings_explanation_wrap_does_not_depend_on_label_configure(self):
        import tkinter as tk
        self.settings.show()
        self.root.update()
        label = next(widget for widget in self.settings.content.winfo_children()
                     if isinstance(widget, tk.Label) and "처음에는" in widget.cget("text"))
        before = label.cget("wraplength")
        with patch.object(label, "configure", wraps=label.configure) as configure:
            label.event_generate("<Configure>", width=73, height=111)
            self.root.update_idletasks()
            configure.assert_not_called()
        self.assertEqual(label.cget("wraplength"), before)
        self.settings.geometry("510x420")
        self.root.update()
        self.assertLess(label.winfo_pixels(label.cget("wraplength")), label.winfo_pixels(before))

    def test_chatter_toggle_preserves_proactive_mode_and_interval_across_reopen(self):
        self.current = replace(self.current, proactive_enabled=False, proactive_interval_minutes=20,
                               weather_location="부산시", conversation_storage_enabled=True)
        self.settings.reload()
        original = self.current
        self.assertFalse(self.settings.chatter.get())
        self.settings.chatter_check.invoke()
        self.settings._hide()
        self.settings.show()
        self.assertTrue(self.settings.chatter.get())
        self.assertTrue(self.settings.dirty)
        self.assertTrue(self.settings._save())
        self.assertEqual(self.current, replace(original, chatter_enabled=True))
        self.settings._hide()
        self.settings.show()
        self.assertTrue(self.settings.chatter.get())
        self.assertFalse(self.settings.proactive.get())
        self.assertEqual(self.settings.proactive_interval.get(), "20")
        self.settings.proactive_check.invoke()
        self.assertTrue(self.settings._save())
        self.assertEqual(self.current, replace(original, chatter_enabled=True, proactive_enabled=True))
        self.settings.chatter_check.invoke()
        self.assertTrue(self.settings._save())
        self.assertEqual(self.current, replace(original, proactive_enabled=True))

    def test_chatter_only_saved_status_requires_ai_and_key_but_not_situation_toggle(self):
        self.current = replace(self.current, enabled=False, proactive_enabled=False, chatter_enabled=True,
                               proactive_events=())
        self.settings.reload()
        self.assertIn("AI 재잘대기 켜짐", self.settings.proactive_state.get())
        self.assertIn("AI 대화 사용을 켜야", self.settings.proactive_state.get())
        self.current = replace(self.current, enabled=True)
        self.settings.reload()
        self.assertIn("API 키 등록", self.settings.proactive_state.get())
        self.has_key = True
        self.settings.reload()
        self.assertNotIn("허용된 상황 없음", self.settings.proactive_state.get())
        self.assertNotIn("정기 응원은 꺼짐", self.settings.proactive_state.get())

    def test_memory_duplicate_selects_existing_and_long_draft_is_kept(self):
        self.memory.add_text.insert("1.0", "오전에는 짧게 답하기")
        self.assertTrue(self.memory._save_editor())
        first = self.memory._selected()
        self.assertIsNotNone(first)
        self.memory.add_text.insert("1.0", "오전에는 짧게 답하기")
        self.assertTrue(self.memory._save_editor())
        self.assertEqual(len(self.service.memory.list_memories()), 1)
        self.assertEqual(self.memory._selected().id, first.id)
        self.assertIn("이미", self.memory.status.get())
        self.memory.add_text.insert("1.0", "가" * 2001)
        self.assertFalse(self.memory._save_editor())
        self.assertEqual(len(self.memory.add_text.get("1.0", "end-1c")), 2001)
        self.assertEqual(len(self.service.memory.list_memories()), 1)

    def test_memory_edit_and_pin_update_selected_record(self):
        first = self.service.memory.add_memory("처음 기억")
        self.memory.refresh(select_ids={first.id})
        self.memory._edit()
        self.memory.add_text.delete("1.0", "end")
        self.memory.add_text.insert("1.0", "수정한 기억")
        self.assertTrue(self.memory._save_editor())
        self.memory._pin()
        stored = self.service.memory.list_memories()
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0].id, first.id)
        self.assertEqual(stored[0].text, "수정한 기억")
        self.assertTrue(stored[0].pinned)
        self.assertEqual(self.service.invalidate_context.call_count, 2)

    def test_memory_selected_delete_does_not_delete_search_hidden_records(self):
        first = self.service.memory.add_memory("업무 기억")
        second = self.service.memory.add_memory("개인 기억")
        self.memory.refresh(select_ids={first.id})
        self.memory.search.set("업무")
        with patch("assistant_ai.ui_memory.messagebox.askyesno", return_value=True) as confirm:
            self.memory._delete()
        self.assertIn("1개", confirm.call_args.args[1])
        self.assertEqual([entry.id for entry in self.service.memory.list_memories()], [second.id])

    def test_memory_refresh_preserves_unsaved_editor(self):
        self.memory.add_text.insert("1.0", "아직 저장하지 않은 기억")
        self.memory.refresh()
        self.assertEqual(self.memory.add_text.get("1.0", "end-1c"), "아직 저장하지 않은 기억")


if __name__ == "__main__":
    unittest.main()
