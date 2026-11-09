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
