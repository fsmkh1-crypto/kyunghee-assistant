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


@dataclass(frozen=True)
class MemoryEntry:
    id: int
    text: str
    created_at: str


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
_TURN_COLUMNS = "id, user_text, assistant_text, created_at"
_MEMORY_COLUMNS = "id, text, created_at"
_Entry = TypeVar("_Entry", ConversationTurn, MemoryEntry)


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
                    generation INTEGER NOT NULL
                );
                INSERT OR IGNORE INTO storage_state VALUES (1, 0, 0);
                CREATE TABLE IF NOT EXISTS conversation_turns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_text TEXT NOT NULL,
                    assistant_text TEXT,
                    created_at TEXT NOT NULL,
                    generation INTEGER NOT NULL
                );
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    normalized_text TEXT NOT NULL UNIQUE,
                    created_at TEXT NOT NULL
                );
            """)

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

    def set_enabled(self, enabled: bool) -> None:
        value = int(bool(enabled))
        with self._connection() as connection:
            connection.execute(
                "UPDATE storage_state SET enabled = ?, generation = generation + 1 WHERE id = 1 AND enabled != ?",
                (value, value),
            )

    def begin_turn(self, text: str) -> int | None:
        text = text.strip()
        if not text:
            return None
        with self._connection() as connection:
            cursor = connection.execute(
                """INSERT INTO conversation_turns (user_text, created_at, generation)
                   SELECT ?, ?, generation FROM storage_state WHERE id = 1 AND enabled = 1""",
                (text, _timestamp()),
            )
            return cursor.lastrowid if cursor.rowcount else None

    def finish_turn(self, turn_id: int, text: str) -> bool:
        text = text.strip()
        if not text:
            return False
        with self._connection() as connection:
            cursor = connection.execute(
                """UPDATE conversation_turns SET assistant_text = ?
                   WHERE id = ? AND assistant_text IS NULL
                   AND generation = (SELECT generation FROM storage_state WHERE id = 1 AND enabled = 1)""",
                (text, turn_id),
            )
            return cursor.rowcount == 1

    @staticmethod
    def _recent(
        connection: sqlite3.Connection, limit: int | None, exclude_id: int | None = None,
    ) -> list[ConversationTurn]:
        rows = connection.execute(
            f"SELECT {_TURN_COLUMNS} FROM conversation_turns WHERE id != ? ORDER BY id DESC LIMIT ?",
            (exclude_id or 0, -1 if limit is None else max(0, limit)),
        ).fetchall()
        return [ConversationTurn(*row) for row in reversed(rows)]

    @staticmethod
    def _turns(connection: sqlite3.Connection, exclude_id: int | None) -> Iterator[ConversationTurn]:
        rows = connection.execute(f"SELECT {_TURN_COLUMNS} FROM conversation_turns WHERE id != ?", (exclude_id or 0,))
        return (ConversationTurn(*row) for row in rows)

    def recent_turns(self, limit: int | None = 20) -> list[ConversationTurn]:
        with self._connection() as connection:
            return self._recent(connection, limit)

    def search_turns(self, query: str, limit: int = 5, *, exclude_id: int | None = None) -> list[ConversationTurn]:
        with self._connection() as connection:
            return _ranked(self._turns(connection, exclude_id), query, limit, _turn_score)

    def add_memory(self, text: str) -> MemoryEntry | None:
        """Save text on explicit user request, returning the existing row for duplicates."""
        text = text.strip()
        if not text:
            return None
        normalized = " ".join(_normalize(text).split())
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if not self._enabled(connection):
                return None
            connection.execute(
                "INSERT OR IGNORE INTO memories (text, normalized_text, created_at) VALUES (?, ?, ?)",
                (text, normalized, _timestamp()),
            )
            row = connection.execute(
                f"SELECT {_MEMORY_COLUMNS} FROM memories WHERE normalized_text = ?", (normalized,),
            ).fetchone()
            return MemoryEntry(*row)

    @staticmethod
    def _memories(connection: sqlite3.Connection) -> Iterator[MemoryEntry]:
        rows = connection.execute(f"SELECT {_MEMORY_COLUMNS} FROM memories ORDER BY id DESC")
        return (MemoryEntry(*row) for row in rows)

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
            if not self._enabled(connection):
                return MemoryContext()
            recent = self._recent(connection, recent_limit, exclude_id)
            memories = tuple(_ranked(self._memories(connection), query, memory_limit, _memory_score))
            return _turn_context(recent, self._turns(connection, exclude_id), query, relevant_limit, memories)

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
        with self._connection() as connection:
            connection.execute("DELETE FROM conversation_turns")
            connection.execute("DELETE FROM memories")


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
            if turn is None or turn.assistant is not None:
                return False
            self._turns[turn_id] = replace(turn, assistant=text)
            return True

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
        turns = self._snapshot(exclude_id)
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
