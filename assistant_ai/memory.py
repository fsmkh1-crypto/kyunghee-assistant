from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import closing, contextmanager
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from heapq import nlargest
import os
from pathlib import Path
import re
import sqlite3
from threading import Lock
from typing import TypeVar
import unicodedata


@dataclass(frozen=True)
class ConversationTurn:
    id: int
    user: str
    assistant: str | None
    created_at: str
    status: str = ""

    def __post_init__(self):
        if not self.status:
            object.__setattr__(self, "status", "completed" if self.assistant is not None else "pending")


@dataclass(frozen=True)
class MemoryEntry:
    id: int
    text: str
    created_at: str
    pinned: bool = False


@dataclass(frozen=True)
class MemoryContext:
    recent: tuple[ConversationTurn, ...] = ()
    relevant: tuple[ConversationTurn, ...] = ()
    memories: tuple[MemoryEntry, ...] = ()


_WORD = re.compile(r"[^\W_]+")
_HANGUL = re.compile(r"[가-힣]+")
_PARTICLES = (
    "에서부터", "으로부터", "에게서", "한테서", "에서는", "으로는", "에서도",
    "이라는", "이라고", "에게는", "한테는", "이라면", "으로도", "으로서",
    "으로써", "에서", "으로", "에게", "한테", "부터", "까지", "보다", "처럼",
    "라는", "라고", "에는", "에도", "이나", "이고", "이며", "로서", "로써",
    "은", "는", "이", "가", "을", "를", "에", "와", "과", "의", "도", "로", "만",
)
_STOP_WORDS = frozenset(
    "아까 알려줘 기억나 기억해 기억해줘 그런데 그리고 그때 그거 내가 다시 대화 대한 대해 "
    "때문에 말해줘 뭐야 뭐였지 무엇 무엇을 어떤 있어 있었지 오늘 우리가 이전 이제 "
    "저번 전에 최근 했어 했지 해줘 the about have what that with when your from".split()
)
_TURN_COLUMNS = "id, user_text, assistant_text, created_at, status"
_MEMORY_COLUMNS = "id, text, created_at, pinned"
_Entry = TypeVar("_Entry", ConversationTurn, MemoryEntry)
MAX_MEMORY_CHARS = 2000
TURN_STATUSES = frozenset({"pending", "completed", "failed", "cancelled", "interrupted"})
_UNANSWERED_STATUSES = TURN_STATUSES - {"pending", "completed"}


def _validate_unanswered_status(status: str) -> None:
    if not isinstance(status, str) or status not in _UNANSWERED_STATUSES:
        raise ValueError("완료되지 않은 대화의 상태를 확인해 주세요.")


class MemoryValidationError(ValueError):
    pass


# Kept as a convenient public alias for callers handling memory input errors.
MemoryError = MemoryValidationError


def validate_memory_text(text: str, *, allow_empty: bool = False) -> str:
    if not isinstance(text, str):
        raise MemoryValidationError("기억할 내용을 글자로 입력해 주세요.")
    text = text.strip()
    if not text and allow_empty:
        return text
    if not 1 <= len(text) <= MAX_MEMORY_CHARS:
        raise MemoryValidationError(f"기억할 내용을 1~{MAX_MEMORY_CHARS:,}자로 입력해 주세요.")
    return text


def _memory_entry(row) -> MemoryEntry:
    return MemoryEntry(row[0], row[1], row[2], bool(row[3]))


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize(text: str) -> str:
    return unicodedata.normalize("NFKC", text).casefold()


def _terms(text: str) -> frozenset[str]:
    terms = set()
    for word in _WORD.findall(_normalize(text)):
        if len(word) < 2 or word in _STOP_WORDS:
            continue
        if _HANGUL.fullmatch(word):
            for suffix in _PARTICLES:
                if len(word) >= len(suffix) + 2 and word.endswith(suffix):
                    word = word[:-len(suffix)]
                    break
        if word not in _STOP_WORDS:
            terms.add(word)
    return frozenset(terms)


def _score(query: frozenset[str], text: str) -> int:
    words = _terms(text)
    score = 4 * len(query & words)
    hangul_words = tuple(word for word in words if _HANGUL.fullmatch(word))
    for term in query - words:
        if _HANGUL.fullmatch(term) and any(term in word or word in term for word in hangul_words):
            score += 1
    return score


def _ranked(
    entries: Iterable[_Entry],
    query: str,
    limit: int,
    score_entry: Callable[[frozenset[str], _Entry], int],
) -> list[_Entry]:
    terms = _terms(query)
    if not terms or limit <= 0:
        return []

    def scored_entries() -> Iterator[tuple[int, _Entry]]:
        for entry in entries:
            score = score_entry(terms, entry)
            if score:
                yield score, entry

    return [entry for _, entry in nlargest(limit, scored_entries(), key=lambda item: (item[0], item[1].id))]


def _turn_score(query: frozenset[str], turn: ConversationTurn) -> int:
    return max(2 * _score(query, turn.user), _score(query, turn.assistant or ""))


def _memory_score(query: frozenset[str], entry: MemoryEntry) -> int:
    return _score(query, entry.text)


def _turn_context(
    recent: list[ConversationTurn],
    older: Iterable[ConversationTurn],
    query: str,
    relevant_limit: int,
    memories: tuple[MemoryEntry, ...] = (),
) -> MemoryContext:
    recent_ids = {turn.id for turn in recent}
    relevant = _ranked((turn for turn in older if turn.id not in recent_ids), query, relevant_limit, _turn_score)
    return MemoryContext(tuple(recent), tuple(relevant), memories)


class MemoryStore:
    """Opt-in conversation history and explicitly saved memories in a local SQLite file."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            pass
        else:
            os.close(fd)
        with self._connection() as connection:
            try:
                connection.execute("PRAGMA journal_mode = WAL").fetchone()
            except sqlite3.OperationalError as error:
                # Another app instance may already be configuring the database.
                if error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                    raise
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE IF NOT EXISTS storage_state (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    enabled INTEGER NOT NULL,
                    generation INTEGER NOT NULL,
                    history_enabled INTEGER NOT NULL DEFAULT 0
                );
                INSERT OR IGNORE INTO storage_state (id, enabled, generation) VALUES (1, 0, 0);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT,
                    created_at TEXT NOT NULL,
                    generation INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending'
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL,
                    pinned INTEGER NOT NULL DEFAULT 0
                );
            """)
            # Migrate in the same transaction; legacy opt-in controlled both features.
            state_columns = {row[1] for row in connection.execute("PRAGMA table_info(storage_state)")}
            if "history_enabled" not in state_columns:
                connection.execute("ALTER TABLE storage_state ADD COLUMN history_enabled INTEGER NOT NULL DEFAULT 0")
                connection.execute("UPDATE storage_state SET history_enabled = enabled")
            memory_columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
            if "pinned" not in memory_columns:
                connection.execute("ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
            turn_columns = {row[1] for row in connection.execute("PRAGMA table_info(conversation_turns)")}
            if "status" not in turn_columns:
                connection.execute("ALTER TABLE conversation_turns ADD COLUMN status TEXT NOT NULL DEFAULT 'pending'")
                connection.execute("UPDATE conversation_turns SET status = CASE "
                                   "WHEN assistant_text IS NULL THEN 'interrupted' ELSE 'completed' END")

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with closing(sqlite3.connect(self.path, timeout=5)) as connection, connection:
            connection.execute("PRAGMA secure_delete = ON")
            yield connection

    @property
    def enabled(self) -> bool:
        with self._connection() as connection:
            return self._enabled(connection)

    @staticmethod
    def _enabled(connection: sqlite3.Connection) -> bool:
        return bool(connection.execute("SELECT enabled FROM storage_state WHERE id = 1").fetchone()[0])

    @property
    def history_enabled(self) -> bool:
        with self._connection() as connection:
            return self._history_enabled(connection)

    @staticmethod
    def _history_enabled(connection: sqlite3.Connection) -> bool:
        return bool(connection.execute("SELECT history_enabled FROM storage_state WHERE id = 1").fetchone()[0])

    def set_enabled(self, enabled: bool) -> None:
        value = int(bool(enabled))
        with self._connection() as connection:
            connection.execute(
                "UPDATE storage_state SET enabled = ? WHERE id = 1 AND enabled != ?",
                (value, value),
            )

    def set_history_enabled(self, enabled: bool) -> None:
        value = int(bool(enabled))
        with self._connection() as connection:
            connection.execute(
                "UPDATE storage_state SET history_enabled = ?, generation = generation + 1 "
                "WHERE id = 1 AND history_enabled != ?", (value, value),
            )

    def begin_turn(self, text: str) -> int | None:
        text = text.strip()
        if not text:
            return None
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO conversation_turns (user_text, created_at, generation)
                   SELECT ?, ?, generation FROM storage_state WHERE id = 1 AND history_enabled = 1""",
                (text, _timestamp()),
            )
            return cursor.lastrowid if cursor.rowcount else None

    def finish_turn(self, turn_id: int, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE conversation_turns SET assistant_text = ?, status = 'completed'
                   WHERE id = ? AND assistant_text IS NULL AND status = 'pending'
                   AND generation = (SELECT generation FROM storage_state WHERE id = 1 AND history_enabled = 1)""",
                (text, turn_id),
            )
            return cursor.rowcount == 1

    def update_turn_status(self, turn_id: int, status: str) -> bool:
        """Mark an unanswered pending turn terminal without adding synthetic dialogue."""
        _validate_unanswered_status(status)
        with self._connection() as connection:
            cursor = connection.execute(
                "UPDATE conversation_turns SET status = ? "
                "WHERE id = ? AND assistant_text IS NULL AND status = 'pending'", (status, turn_id),
            )
            return cursor.rowcount == 1

    def mark_interrupted_turns(self) -> int:
        """Call once at app startup after confirming no previous worker remains active."""
        with self._connection() as connection:
            return connection.execute(
                "UPDATE conversation_turns SET status = 'interrupted' "
                "WHERE assistant_text IS NULL AND status = 'pending'",
            ).rowcount

    @staticmethod
    def _recent(
        connection: sqlite3.Connection, limit: int | None, exclude_id: int | None = None,
        *, completed_only: bool = False,
    ) -> list[ConversationTurn]:
        status_filter = " AND status = 'completed'" if completed_only else ""
        rows = connection.execute(
            f"SELECT {_TURN_COLUMNS} FROM conversation_turns WHERE id != ?{status_filter} ORDER BY id DESC LIMIT ?",
            (exclude_id or 0, -1 if limit is None else max(0, limit)),
        ).fetchall()
        return [ConversationTurn(*row) for row in reversed(rows)]

    @staticmethod
    def _turns(
        connection: sqlite3.Connection, exclude_id: int | None, *, completed_only: bool = False,
    ) -> Iterator[ConversationTurn]:
        status_filter = " AND status = 'completed'" if completed_only else ""
        rows = connection.execute(
            f"SELECT {_TURN_COLUMNS} FROM conversation_turns WHERE id != ?{status_filter}", (exclude_id or 0,),
        )
        return (ConversationTurn(*row) for row in rows)

    def recent_turns(self, limit: int | None = 20) -> list[ConversationTurn]:
        with self._connection() as connection:
            return self._recent(connection, limit)

    def search_turns(self, query: str, limit: int = 5, *, exclude_id: int | None = None) -> list[ConversationTurn]:
        with self._connection() as connection:
            return _ranked(self._turns(connection, exclude_id), query, limit, _turn_score)

    def add_memory(self, text: str) -> MemoryEntry | None:
        """Save text on explicit user request, returning the existing row for duplicates."""
        return self.add_memory_with_result(text)[0]

    def add_memory_with_result(self, text: str) -> tuple[MemoryEntry | None, bool]:
        """Return the saved entry and whether it was newly created."""
        text = validate_memory_text(text, allow_empty=True)
        if not text:
            return None, False
        normalized = " ".join(_normalize(text).split())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._enabled(connection):
                return None, False
            cursor = connection.execute(
                "INSERT OR IGNORE INTO memories (text, normalized_text, created_at) VALUES (?, ?, ?)",
                (text, normalized, _timestamp()),
            )
            row = connection.execute(
                f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE normalized_text = ?", (normalized,),
            ).fetchone()
            return _memory_entry(row), cursor.rowcount == 1

    def update_memory(self, memory_id: int, text: str) -> MemoryEntry | None:
        text = validate_memory_text(text)
        normalized = " ".join(_normalize(text).split())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            duplicate = connection.execute(
                "SELECT id FROM memories WHERE normalized_text = ? AND id != ?", (normalized, memory_id),
            ).fetchone()
            if duplicate:
                raise MemoryValidationError("같은 내용의 기억이 이미 있어요. 기존 기억을 선택해 주세요.")
            connection.execute(
                "UPDATE memories SET text = ?, normalized_text = ? WHERE id = ?", (text, normalized, memory_id),
            )
            row = connection.execute(f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE id = ?", (memory_id,)).fetchone()
            return _memory_entry(row) if row else None

    def set_memory_pinned(self, memory_id: int, pinned: bool) -> MemoryEntry | None:
        if type(pinned) is not bool:
            raise MemoryValidationError("기억 고정 여부를 다시 선택해 주세요.")
        with self._connection() as connection:
            connection.execute("UPDATE memories SET pinned = ? WHERE id = ?", (int(pinned), memory_id))
            row = connection.execute(f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE id = ?", (memory_id,)).fetchone()
            return _memory_entry(row) if row else None

    @staticmethod
    def _memories(connection: sqlite3.Connection) -> Iterator[MemoryEntry]:
        rows = connection.execute(f"SELECT {_MEMORY_COLUMNS} FROM memories ORDER BY pinned DESC, id DESC")
        return (_memory_entry(row) for row in rows)

    def list_memories(self) -> list[MemoryEntry]:
        with self._connection() as connection:
            return list(self._memories(connection))

    def search_memories(self, query: str, limit: int = 5) -> list[MemoryEntry]:
        with self._connection() as connection:
            return _ranked(self._memories(connection), query, limit, _memory_score)

    def context(
        self, query: str, *, exclude_id: int | None = None, recent_limit: int = 6,
        relevant_limit: int = 4, memory_limit: int = 6,
    ) -> MemoryContext:
        with self._connection() as connection:
            connection.execute("BEGIN")
            memories = ()
            if self._enabled(connection):
                entries = list(self._memories(connection))
                pinned = [entry for entry in entries if entry.pinned]
                relevant = _ranked(
                    (entry for entry in entries if not entry.pinned), query,
                    max(0, memory_limit - len(pinned)), _memory_score,
                )
                memories = tuple(pinned + relevant)
            if not self._history_enabled(connection):
                return MemoryContext(memories=memories)
            recent = self._recent(connection, recent_limit, exclude_id, completed_only=True)
            return _turn_context(
                recent, self._turns(connection, exclude_id, completed_only=True), query, relevant_limit, memories,
            )

    def counts(self) -> dict[str, int]:
        with self._connection() as connection:
            connection.execute("BEGIN")
            return {name: connection.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                    for name in ("conversation_turns", "memories")}

    def clear_data(self, *, conversations: bool = False, memories: bool = False) -> dict[str, int]:
        deleted = {"conversation_turns": 0, "memories": 0}
        with self._connection() as connection:
            if conversations:
                deleted["conversation_turns"] = connection.execute("DELETE FROM conversation_turns").rowcount
            if memories:
                deleted["memories"] = connection.execute("DELETE FROM memories").rowcount
        return deleted

    def delete_turn(self, turn_id: int) -> bool:
        with self._connection() as connection:
            return connection.execute("DELETE FROM conversation_turns WHERE id = ?", (turn_id,)).rowcount == 1

    def delete_memory(self, memory_id: int) -> bool:
        with self._connection() as connection:
            return connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,)).rowcount == 1

    def clear_history(self) -> int:
        with self._connection() as connection:
            return connection.execute("DELETE FROM conversation_turns").rowcount

    def clear_memories(self) -> int:
        with self._connection() as connection:
            return connection.execute("DELETE FROM memories").rowcount

    def clear_all(self) -> None:
        self.clear_data(conversations=True, memories=True)


class SessionHistory:
    """Keep conversation continuity in RAM when persistent storage is off."""

    def __init__(self):
        self._lock = Lock()
        self._turns: dict[int, ConversationTurn] = {}
        self._next_id = 1

    def begin_turn(self, text: str) -> int | None:
        text = text.strip()
        if not text:
            return None
        with self._lock:
            turn_id = self._next_id
            self._next_id += 1
            self._turns[turn_id] = ConversationTurn(turn_id, text, None, _timestamp())
            return turn_id

    def finish_turn(self, turn_id: int, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None or turn.assistant is not None or turn.status != "pending":
                return False
            self._turns[turn_id] = replace(turn, assistant=text, status="completed")
            return True

    def update_turn_status(self, turn_id: int, status: str) -> bool:
        _validate_unanswered_status(status)
        with self._lock:
            turn = self._turns.get(turn_id)
            if turn is None or turn.assistant is not None or turn.status != "pending":
                return False
            self._turns[turn_id] = replace(turn, status=status)
            return True

    def mark_interrupted_turns(self) -> int:
        with self._lock:
            pending = [turn for turn in self._turns.values() if turn.status == "pending" and turn.assistant is None]
            for turn in pending:
                self._turns[turn.id] = replace(turn, status="interrupted")
            return len(pending)

    def _snapshot(self, exclude_id: int | None = None) -> list[ConversationTurn]:
        with self._lock:
            return [turn for turn in self._turns.values() if turn.id != exclude_id]

    def recent_turns(self, limit: int | None = 20) -> list[ConversationTurn]:
        if limit is None:
            return self._snapshot()
        return self._snapshot()[-limit:] if limit > 0 else []

    def search_turns(self, query: str, limit: int = 5, *, exclude_id: int | None = None) -> list[ConversationTurn]:
        return _ranked(self._snapshot(exclude_id), query, limit, _turn_score)

    def context(
        self, query: str, *, exclude_id: int | None = None, recent_limit: int = 6,
        relevant_limit: int = 4, memory_limit: int = 6,
    ) -> MemoryContext:
        turns = [turn for turn in self._snapshot(exclude_id) if turn.status == "completed"]
        recent = turns[-recent_limit:] if recent_limit > 0 else []
        return _turn_context(recent, turns, query, relevant_limit)

    def delete_turn(self, turn_id: int) -> bool:
        with self._lock:
            return self._turns.pop(turn_id, None) is not None

    def clear_history(self) -> int:
        with self._lock:
            count = len(self._turns)
            self._turns.clear()
            return count
