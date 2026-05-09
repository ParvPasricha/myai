"""
Episodic memory — Layer 2.

Stores every conversation turn permanently in SQLite with FTS5 full-text search.
Never deleted — this is the raw historical record.

Schema:
    conversations(id, session_id, timestamp, role, content, summary, intent_category)
    events(id, timestamp, type, description, metadata_json)
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent.parent / "memory" / "episodic.db"
_DB_PATH.parent.mkdir(exist_ok=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id       TEXT NOT NULL,
            timestamp        REAL NOT NULL,
            role             TEXT NOT NULL,       -- user | assistant | system
            content          TEXT NOT NULL,
            summary          TEXT,                -- filled by nightly distillation
            intent_category  TEXT                 -- filled by intent extractor
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
            content,
            content='conversations',
            content_rowid='id'
        );

        CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
            INSERT INTO conversations_fts(rowid, content) VALUES (new.id, new.content);
        END;

        CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
            INSERT INTO conversations_fts(conversations_fts, rowid, content)
            VALUES ('delete', old.id, old.content);
        END;

        CREATE TABLE IF NOT EXISTS events (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp     REAL NOT NULL,
            type          TEXT NOT NULL,
            description   TEXT NOT NULL,
            metadata_json TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_conv_session   ON conversations(session_id);
        CREATE INDEX IF NOT EXISTS idx_conv_timestamp ON conversations(timestamp);
        CREATE INDEX IF NOT EXISTS idx_events_type    ON events(type);
        """)


# ── Conversations ─────────────────────────────────────────────────────────────

def log_message(session_id: str, role: str, content: str,
                intent_category: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO conversations (session_id, timestamp, role, content, intent_category) VALUES (?,?,?,?,?)",
            (session_id, time.time(), role, content, intent_category),
        )
        return cur.lastrowid


def get_session(session_id: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM conversations WHERE session_id = ? ORDER BY timestamp",
            (session_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_recent(hours: int = 24, limit: int = 200) -> list[dict]:
    since = time.time() - hours * 3600
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM conversations WHERE timestamp > ? ORDER BY timestamp DESC LIMIT ?",
            (since, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def search(query: str, limit: int = 10) -> list[dict]:
    """Full-text search over conversation content."""
    with _conn() as c:
        rows = c.execute(
            """
            SELECT c.* FROM conversations c
            JOIN conversations_fts f ON c.id = f.rowid
            WHERE conversations_fts MATCH ?
            ORDER BY rank
            LIMIT ?
            """,
            (query, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def set_summary(session_id: str, summary: str):
    """Set the summary for all messages in a session (written by distillation)."""
    with _conn() as c:
        c.execute(
            "UPDATE conversations SET summary = ? WHERE session_id = ?",
            (summary, session_id),
        )


# ── Events ────────────────────────────────────────────────────────────────────

def log_event(event_type: str, description: str, metadata: dict | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO events (timestamp, type, description, metadata_json) VALUES (?,?,?,?)",
            (time.time(), event_type, description, json.dumps(metadata) if metadata else None),
        )
        return cur.lastrowid


def get_events(event_type: str | None = None, hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    with _conn() as c:
        if event_type:
            rows = c.execute(
                "SELECT * FROM events WHERE type = ? AND timestamp > ? ORDER BY timestamp DESC",
                (event_type, since),
            ).fetchall()
        else:
            rows = c.execute(
                "SELECT * FROM events WHERE timestamp > ? ORDER BY timestamp DESC",
                (since,),
            ).fetchall()
        return [dict(r) for r in rows]


migrate()
