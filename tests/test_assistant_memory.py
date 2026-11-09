from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
import unittest

from assistant_ai.memory import MemoryContext, MemoryStore, SessionHistory


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
        topical = self.store.begin_turn("방문판매법을 읽어 봤어요.")
        unrelated = self.store.begin_turn("일요일에는 등산을 가요.")
        recent = self.store.begin_turn("오늘 일정부터 확인하자.")
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
        pending = self.store.begin_turn("계약서")
        saved = self.store.add_memory("계약서는 금요일까지")
        self.store.set_enabled(False)
        self.assertEqual(self.store.context("계약서"), MemoryContext())
        self.assertEqual(self.store.list_memories(), [saved])
        self.assertEqual(self.store.recent_turns()[0].id, pending)
        self.assertIsNone(self.store.begin_turn("저장하지 않아요"))
        self.assertIsNone(self.store.add_memory("저장하지 않아요"))
        self.assertFalse(self.store.finish_turn(pending, "오래된 답변"))
        self.assertTrue(self.store.delete_memory(saved.id))

        self.store.set_enabled(True)
        self.assertFalse(self.store.finish_turn(pending, "오래된 답변"))
        self.assertTrue(self.store.delete_turn(pending))
        self.assertEqual(self.store.context("계약서"), MemoryContext())

    def test_explicit_memory_is_deduplicated_and_never_reextracted_from_history(self):
        self.store.set_enabled(True)
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


class SessionHistoryTests(unittest.TestCase):
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
