import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from app.models import ReplyMetadata, StoredMessage

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    session_id TEXT PRIMARY KEY,
    system_prompt TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(session_id),
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    metadata TEXT,
    created_at TEXT NOT NULL,
    CHECK ((role = 'user' AND metadata IS NULL) OR
           (role = 'assistant' AND metadata IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_messages_session_order ON messages(session_id, id);
"""


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA)

    def check_health(self) -> None:
        with self.connection() as connection:
            connection.execute("SELECT count(*) FROM sessions").fetchone()

    def load_session(self, session_id: str) -> tuple[str | None, list[StoredMessage]]:
        with self.connection() as connection:
            session = connection.execute(
                "SELECT system_prompt FROM sessions WHERE session_id = ?", (session_id,)
            ).fetchone()
            if session is None:
                return None, []
            rows = connection.execute(
                "SELECT role, content, metadata FROM messages WHERE session_id = ? ORDER BY id",
                (session_id,),
            ).fetchall()

        messages = [
            StoredMessage(
                role=row["role"],
                content=row["content"],
                metadata=ReplyMetadata.model_validate(json.loads(row["metadata"]))
                if row["metadata"] is not None
                else None,
            )
            for row in rows
        ]
        return session["system_prompt"], messages

    def save_turn(
        self,
        session_id: str,
        system_prompt: str,
        message: str,
        reply: str,
        metadata: ReplyMetadata,
    ) -> None:
        created_at = datetime.now(UTC).isoformat()
        with self.connection() as connection:
            connection.execute(
                """INSERT INTO sessions(session_id, system_prompt, created_at) VALUES (?, ?, ?)
                   ON CONFLICT(session_id) DO UPDATE SET system_prompt = excluded.system_prompt""",
                (session_id, system_prompt, created_at),
            )
            connection.executemany(
                """INSERT INTO messages(session_id, role, content, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?)""",
                [
                    (session_id, "user", message, None, created_at),
                    (session_id, "assistant", reply, metadata.model_dump_json(), created_at),
                ],
            )
