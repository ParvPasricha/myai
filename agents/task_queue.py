"""
Agent task queue — SQLite backed.

Tables:
  agent_tasks   — all tasks ever dispatched
  agent_results — results written by subagents
"""
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

_DB_PATH = Path(__file__).parent.parent / "memory" / "agents.db"

_sqlite: Optional[sqlite3.Connection] = None


def _db() -> sqlite3.Connection:
    global _sqlite
    if _sqlite is None:
        _sqlite = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _sqlite.row_factory = sqlite3.Row
        _sqlite.executescript("""
            CREATE TABLE IF NOT EXISTS agent_tasks (
                id            TEXT PRIMARY KEY,
                created_at    REAL NOT NULL,
                priority      INTEGER DEFAULT 5,
                status        TEXT DEFAULT 'pending',   -- pending|running|done|failed|cancelled
                task_type     TEXT NOT NULL,
                payload       TEXT DEFAULT '{}',
                assigned_to   TEXT DEFAULT '',
                parent_id     TEXT DEFAULT '',
                expires_at    REAL
            );
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON agent_tasks(status, priority);

            CREATE TABLE IF NOT EXISTS agent_results (
                id            TEXT PRIMARY KEY,
                task_id       TEXT NOT NULL REFERENCES agent_tasks(id),
                agent_name    TEXT NOT NULL,
                success       INTEGER NOT NULL,
                data          TEXT DEFAULT '{}',
                summary       TEXT DEFAULT '',
                error         TEXT DEFAULT '',
                created_at    REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_results_task ON agent_results(task_id);
        """)
        _sqlite.commit()
    return _sqlite


def enqueue(
    task_type: str,
    payload: dict,
    priority: int = 5,
    parent_id: str = "",
    expires_in: Optional[float] = None,
) -> str:
    task_id = uuid.uuid4().hex[:10]
    db = _db()
    db.execute(
        """INSERT INTO agent_tasks
           (id, created_at, priority, status, task_type, payload, parent_id, expires_at)
           VALUES (?, ?, ?, 'pending', ?, ?, ?, ?)""",
        (
            task_id, time.time(), priority,
            task_type, json.dumps(payload), parent_id,
            time.time() + expires_in if expires_in else None,
        ),
    )
    db.commit()
    return task_id


def claim(task_type: Optional[str] = None) -> Optional[dict]:
    """Atomically claim the next pending task. Returns task dict or None."""
    db = _db()
    where = "status='pending'" + (f" AND task_type='{task_type}'" if task_type else "")
    row = db.execute(
        f"SELECT * FROM agent_tasks WHERE {where} ORDER BY priority, created_at LIMIT 1"
    ).fetchone()
    if not row:
        return None
    db.execute("UPDATE agent_tasks SET status='running' WHERE id=?", (row["id"],))
    db.commit()
    return dict(row)


def complete(task_id: str, agent_name: str, success: bool,
             data: dict, summary: str, error: str = "") -> None:
    db = _db()
    result_id = uuid.uuid4().hex[:10]
    db.execute(
        """INSERT INTO agent_results
           (id, task_id, agent_name, success, data, summary, error, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (result_id, task_id, agent_name, int(success),
         json.dumps(data), summary, error, time.time()),
    )
    db.execute(
        "UPDATE agent_tasks SET status=?, assigned_to=? WHERE id=?",
        ("done" if success else "failed", agent_name, task_id),
    )
    db.commit()


def fail(task_id: str, error: str) -> None:
    _db().execute(
        "UPDATE agent_tasks SET status='failed' WHERE id=?", (task_id,)
    )
    _db().commit()


def get_task(task_id: str) -> Optional[dict]:
    row = _db().execute(
        "SELECT * FROM agent_tasks WHERE id=?", (task_id,)
    ).fetchone()
    return dict(row) if row else None


def get_results(task_id: str) -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM agent_results WHERE task_id=?", (task_id,)
    ).fetchall()
    return [dict(r) for r in rows]


def recent_tasks(limit: int = 20) -> list[dict]:
    rows = _db().execute(
        "SELECT * FROM agent_tasks ORDER BY created_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [dict(r) for r in rows]


def pending_count() -> int:
    row = _db().execute(
        "SELECT COUNT(*) as n FROM agent_tasks WHERE status='pending'"
    ).fetchone()
    return row["n"] if row else 0
