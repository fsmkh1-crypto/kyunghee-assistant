from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Barrier, Event
import sqlite3
import unittest

from assistant_ai.memory import (
    MAX_MEMORY_CHARS, ConversationTurn, MemoryContext, MemoryStore, MemoryValidationError, SessionHistory,
)


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = Path(directory.name) / "assistant" / "memory.sqlite3"
        self.store = MemoryStore(self.path)

    def test_persistence_is_opt_in_and_survives_reopen(self):
        self.assertFalse(self.store.enabled)
        self.assertIsNone(self.store.begin_turn("대화"))
        self.assertIsNone(self.store.add_memory("기억"))
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        first = self.store.begin_turn("계약서 검토를 시작하자.")
        second = self.store.begin_turn("다음 업무는?")
        self.assertTrue(self.store.finish_turn(first, "계약서 초안을 검토해요."))
        self.assertFalse(self.store.finish_turn(first, "중복 응답"))
        saved = self.store.add_memory("검토는 오전에 먼저 한다.")

        reopened = MemoryStore(self.path)
        self.assertTrue(reopened.enabled)
        turns = reopened.recent_turns(limit=None)
        self.assertEqual([turn.id for turn in turns], [first, second])
        self.assertEqual(turns[0].user, "계약서 검토를 시작하자.")
        self.assertEqual(turns[0].assistant, "계약서 초안을 검토해요.")
        self.assertIsNone(turns[1].assistant)
        self.assertEqual(reopened.list_memories(), [saved])

    def test_context_uses_korean_terms_and_excludes_duplicate_and_active_turns(self):
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        topical = self.store.begin_turn("방문판매법을 읽어 봤어요.")
        unrelated = self.store.begin_turn("일요일에는 등산을 가요.")
        recent = self.store.begin_turn("오늘 일정부터 확인하자.")
        for turn_id in (topical, unrelated, recent):
            self.store.finish_turn(turn_id, "확인했어요.")
        query = "방문판매법이 뭐였지?"
        active = self.store.begin_turn(query)
        saved = self.store.add_memory("방문판매법은 업무 관련 기준이에요.")
        self.store.add_memory("등산화는 현관에 있어요.")

        context = self.store.context(query, exclude_id=active, recent_limit=1)
        self.assertEqual([turn.id for turn in context.recent], [recent])
        self.assertEqual([turn.id for turn in context.relevant], [topical])
        self.assertEqual(context.memories, (saved,))
        self.assertEqual(self.store.search_turns("등산")[0].id, unrelated)
        self.assertEqual(self.store.search_turns("뭐였지?"), [])

    def test_disabled_storage_keeps_records_manageable_and_blocks_stale_answers(self):
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        pending = self.store.begin_turn("계약서")
        saved = self.store.add_memory("계약서는 금요일까지")
        self.store.set_enabled(False)
        self.store.set_history_enabled(False)
        self.assertEqual(self.store.context("계약서"), MemoryContext())
        self.assertEqual(self.store.list_memories(), [saved])
        self.assertEqual(self.store.recent_turns()[0].id, pending)
        self.assertIsNone(self.store.begin_turn("저장하지 않아요"))
        self.assertIsNone(self.store.add_memory("저장하지 않아요"))
        self.assertFalse(self.store.finish_turn(pending, "오래된 답변"))
        self.assertTrue(self.store.delete_memory(saved.id))

        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        self.assertFalse(self.store.finish_turn(pending, "오래된 답변"))
        self.assertTrue(self.store.delete_turn(pending))
        self.assertEqual(self.store.context("계약서"), MemoryContext())

    def test_explicit_memory_is_deduplicated_and_never_reextracted_from_history(self):
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        self.store.begin_turn("중요한 OpenAI 메모를 기억해 줘.")
        self.assertEqual(self.store.list_memories(), [])
        saved = self.store.add_memory("OpenAI 메모")
        duplicate = self.store.add_memory("  ＯＰＥＮＡＩ  메모  ")
        self.assertEqual(duplicate, saved)
        self.assertEqual(self.store.search_memories("openai"), [saved])
        self.assertTrue(self.store.delete_memory(saved.id))
        self.assertEqual(self.store.context("OpenAI").memories, ())
        self.assertEqual(MemoryStore(self.path).list_memories(), [])

    def test_worker_cannot_restore_turn_after_clear_or_delete(self):
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        for remove in (self.store.delete_turn, lambda _: self.store.clear_all()):
            pending = self.store.begin_turn("삭제할 대화")
            ready = Event()
            resume = Event()

            def reply():
                worker_store = MemoryStore(self.path)
                ready.set()
                if not resume.wait(5):
                    raise TimeoutError("Worker did not receive resume signal")
                return worker_store.finish_turn(pending, "늦게 도착한 답변")

            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(reply)
                try:
                    self.assertTrue(ready.wait(5))
                    remove(pending)
                finally:
                    resume.set()
                self.assertFalse(future.result())

        replacement = self.store.begin_turn("새 대화")
        self.assertGreater(replacement, pending)
        self.assertTrue(self.store.finish_turn(replacement, "새 답변"))
        self.assertEqual([turn.id for turn in self.store.recent_turns()], [replacement])

    def test_history_and_memory_choices_are_independent(self):
        self.store.set_enabled(True)
        self.assertIsNone(self.store.begin_turn("대화를 저장하지 않아요"))
        saved = self.store.add_memory("항상 짧게 답해 주세요")
        self.store.set_memory_pinned(saved.id, True)
        self.assertEqual(self.store.context("상관없는 질문").memories[0].id, saved.id)
        self.assertEqual(self.store.context("상관없는 질문").recent, ())
        self.store.set_enabled(False)
        self.store.set_history_enabled(True)
        turn = self.store.begin_turn("대화는 보관해요")
        self.assertTrue(self.store.finish_turn(turn, "확인했어요"))
        self.assertIsNone(self.store.add_memory("새 기억은 저장하지 않아요"))
        context = self.store.context("대화")
        self.assertEqual([entry.id for entry in context.recent], [turn])
        self.assertEqual(context.memories, ())
        self.assertEqual(self.store.counts(), {"conversation_turns": 1, "memories": 1})

    def test_legacy_database_migration_preserves_both_opt_ins_and_data(self):
        path = self.path.with_name("legacy.sqlite3")
        with closing(sqlite3.connect(path)) as connection, connection:
            connection.executescript("""
                CREATE TABLE storage_state (id INTEGER PRIMARY KEY, enabled INTEGER NOT NULL, generation INTEGER NOT NULL);
                INSERT INTO storage_state VALUES (1, 1, 3);
                CREATE TABLE conversation_turns (id INTEGER PRIMARY KEY AUTOINCREMENT, user_text TEXT NOT NULL,
                    assistant_text TEXT, created_at TEXT NOT NULL, generation INTEGER NOT NULL);
                INSERT INTO conversation_turns VALUES (4, '이전 대화', '이전 답변', '2026-11-09T00:00:00+00:00', 3);
                INSERT INTO conversation_turns VALUES (5, '이전 미완료 대화', NULL, '2026-11-09T01:00:00+00:00', 3);
                CREATE TABLE memories (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL UNIQUE, created_at TEXT NOT NULL);
                INSERT INTO memories VALUES (7, '이전 기억', '이전 기억', '2026-11-09T00:00:00+00:00');
            """)
        migrated = MemoryStore(path)
        self.assertTrue(migrated.enabled)
        self.assertTrue(migrated.history_enabled)
        self.assertEqual(migrated.recent_turns()[0].id, 4)
        self.assertEqual([turn.status for turn in migrated.recent_turns()], ["completed", "interrupted"])
        self.assertEqual(migrated.recent_turns()[1].user, "이전 미완료 대화")
        self.assertIsNone(migrated.recent_turns()[1].assistant)
        self.assertEqual(migrated.list_memories()[0].id, 7)
        self.assertFalse(migrated.list_memories()[0].pinned)
        migrated.set_history_enabled(False)
        self.assertFalse(MemoryStore(path).history_enabled)
        self.assertEqual(MemoryStore(path).counts(), {"conversation_turns": 2, "memories": 1})

    def test_edit_pin_deduplicate_and_length_validation_share_one_path(self):
        self.store.set_enabled(True)
        original, created = self.store.add_memory_with_result("첫 기억")
        self.assertTrue(created)
        duplicate, created = self.store.add_memory_with_result("  첫   기억  ")
        self.assertFalse(created)
        self.assertEqual(duplicate, original)
        pinned = self.store.set_memory_pinned(original.id, True)
        edited = self.store.update_memory(original.id, "항상 간결하게 답변")
        self.assertTrue(pinned.pinned)
        self.assertTrue(edited.pinned)
        self.assertEqual(edited.created_at, original.created_at)
        self.assertEqual(self.store.context("고양이", memory_limit=0).memories, (edited,))
        other = self.store.add_memory("다른 기억")
        with self.assertRaises(MemoryValidationError):
            self.store.update_memory(other.id, "항상 간결하게 답변")
        self.assertEqual(len(self.store.list_memories()), 2)
        for invalid in ("x" * (MAX_MEMORY_CHARS + 1), None):
            with self.subTest(invalid_type=type(invalid).__name__):
                with self.assertRaises(MemoryValidationError):
                    self.store.add_memory(invalid)
                with self.assertRaises(MemoryValidationError):
                    self.store.update_memory(original.id, invalid)
        self.assertIsNone(self.store.update_memory(9999, "없는 기억"))
        self.assertIsNone(self.store.set_memory_pinned(9999, True))
        self.assertTrue(MemoryStore(self.path).list_memories()[0].pinned)

    def test_scoped_delete_reports_counts_and_does_not_delete_other_scope(self):
        self.store.set_enabled(True)
        self.store.set_history_enabled(True)
        pending = self.store.begin_turn("지울 대화")
        self.store.add_memory("남길 기억")
        self.assertEqual(self.store.clear_data(conversations=True), {"conversation_turns": 1, "memories": 0})
        self.assertFalse(self.store.finish_turn(pending, "뒤늦은 답변"))
        self.assertEqual(self.store.counts(), {"conversation_turns": 0, "memories": 1})
        self.assertEqual(self.store.clear_data(memories=True), {"conversation_turns": 0, "memories": 1})

    def test_failure_and_cancellation_are_metadata_and_block_late_answers(self):
        self.store.set_history_enabled(True)
        for history in (self.store, SessionHistory()):
            with self.subTest(history=type(history).__name__):
                for status in ("failed", "cancelled", "interrupted"):
                    turn_id = history.begin_turn("원래 요청 " + status)
                    self.assertEqual(history.recent_turns()[-1].status, "pending")
                    self.assertTrue(history.update_turn_status(turn_id, status))
                    self.assertFalse(history.finish_turn(turn_id, "뒤늦은 응답"))
                    self.assertFalse(history.update_turn_status(turn_id, "failed"))
                    turn = history.recent_turns()[-1]
                    self.assertEqual(turn.user, "원래 요청 " + status)
                    self.assertIsNone(turn.assistant)
                    self.assertEqual(turn.status, status)
                completed = history.begin_turn("완료할 요청")
                self.assertTrue(history.finish_turn(completed, "실제 응답"))
                self.assertFalse(history.update_turn_status(completed, "cancelled"))
                self.assertEqual(history.recent_turns()[-1].status, "completed")
                self.assertEqual(history.recent_turns()[-1].assistant, "실제 응답")
                for invalid in ("pending", "completed", "unknown", None):
                    with self.assertRaises(ValueError):
                        history.update_turn_status(completed, invalid)
                history.delete_turn(completed)
                self.assertFalse(history.update_turn_status(completed, "failed"))

    def test_restart_interrupt_is_explicit_and_does_not_change_terminal_statuses(self):
        self.store.set_history_enabled(True)
        pending = self.store.begin_turn("앱 종료 전 처리 중")
        failed = self.store.begin_turn("실패한 요청")
        self.store.update_turn_status(failed, "failed")
        reopened = MemoryStore(self.path)
        self.assertEqual(reopened.recent_turns()[0].status, "pending")
        self.assertEqual(reopened.mark_interrupted_turns(), 1)
        self.assertEqual(reopened.mark_interrupted_turns(), 0)
        self.assertEqual([turn.status for turn in reopened.recent_turns()], ["interrupted", "failed"])
        self.assertFalse(self.store.finish_turn(pending, "재시작 뒤 늦은 응답"))

    def test_model_context_excludes_unfinished_turns_without_hiding_history(self):
        self.store.set_history_enabled(True)
        for history in (self.store, SessionHistory()):
            with self.subTest(history=type(history).__name__):
                completed = history.begin_turn("완료된 계약서 검토")
                history.finish_turn(completed, "계약서 검토 결과")
                for status in ("failed", "cancelled", "interrupted", "pending"):
                    turn_id = history.begin_turn("계약서 삭제 " + status)
                    if status != "pending":
                        history.update_turn_status(turn_id, status)
                self.assertEqual(len(history.recent_turns()), 5)
                context = history.context("계약서", recent_limit=1)
                self.assertEqual([turn.id for turn in context.recent], [completed])
                self.assertEqual(context.relevant, ())
                relevant = history.context("계약서", recent_limit=0)
                self.assertEqual([turn.id for turn in relevant.relevant], [completed])

    def test_finish_and_cancel_race_has_one_winner(self):
        self.store.set_history_enabled(True)
        for history in (self.store, SessionHistory()):
            with self.subTest(history=type(history).__name__):
                turn_id = history.begin_turn("동시에 완료 또는 취소")
                gate = Barrier(2)

                def finish():
                    gate.wait(timeout=5)
                    return history.finish_turn(turn_id, "실제 응답")

                def cancel():
                    gate.wait(timeout=5)
                    return history.update_turn_status(turn_id, "cancelled")

                with ThreadPoolExecutor(max_workers=2) as workers:
                    done = workers.submit(finish)
                    cancelled = workers.submit(cancel)
                    results = (done.result(timeout=5), cancelled.result(timeout=5))
                self.assertEqual(sum(results), 1)
                turn = history.recent_turns()[-1]
                self.assertEqual((turn.status, turn.assistant),
                                 ("completed", "실제 응답") if results[0] else ("cancelled", None))


class SessionHistoryTests(unittest.TestCase):
    def test_legacy_turn_construction_derives_status_without_changing_text(self):
        self.assertEqual(ConversationTurn(1, "질문", "답변", "timestamp").status, "completed")
        self.assertEqual(ConversationTurn(2, "질문", None, "timestamp").status, "pending")

    def test_session_keeps_context_and_discards_deleted_pending_turns(self):
        history = SessionHistory()
        first = history.begin_turn("서류를 확인해 주세요.")
        self.assertTrue(history.finish_turn(first, "서류 검토를 마쳤어요."))
        current = history.begin_turn("서류 검토에 대해 알려줘.")
        context = history.context("서류", exclude_id=current)
        self.assertEqual([turn.id for turn in context.recent], [first])
        self.assertEqual(context.memories, ())
        self.assertEqual([turn.id for turn in history.recent_turns(limit=None)], [first, current])
        self.assertEqual(history.clear_history(), 2)
        self.assertFalse(history.finish_turn(current, "삭제 이후의 답변"))
        self.assertGreater(history.begin_turn("새 대화"), current)
        self.assertEqual(SessionHistory().recent_turns(), [])


if __name__ == "__main__":
    unittest.main()
