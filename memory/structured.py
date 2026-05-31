"""
Structured memory — Layer 4.

Primary store: PostgreSQL (via db/postgres.py).
Fallback:      SQLite (memory/structured.db) if Postgres is unreachable.

The public API is identical regardless of which backend is active —
callers never need to know which one is running.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

# ── Backend selection ─────────────────────────────────────────────────────────

_USING_POSTGRES = False
_pg = None

def _init_backend():
    global _USING_POSTGRES, _pg
    try:
        from db import postgres
        postgres.migrate()
        postgres.ping()
        _pg = postgres
        _USING_POSTGRES = True
    except Exception:
        _USING_POSTGRES = False

_init_backend()


# ── SQLite fallback ───────────────────────────────────────────────────────────

_DB_PATH = Path(__file__).parent.parent / "memory" / "structured.db"
_DB_PATH.parent.mkdir(exist_ok=True)

_sqlite_conn: sqlite3.Connection | None = None

def _conn() -> sqlite3.Connection:
    global _sqlite_conn
    if _sqlite_conn is None:
        _sqlite_conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _sqlite_conn.row_factory = sqlite3.Row
        _sqlite_conn.execute("PRAGMA journal_mode=WAL")
        _sqlite_conn.execute("PRAGMA synchronous=NORMAL")
    return _sqlite_conn


def _sq(sql_pg: str, sql_lite: str, params: tuple = ()) -> list[dict]:
    """Run a SELECT — Postgres first, SQLite fallback."""
    if _USING_POSTGRES:
        return _pg.query(sql_pg, params)
    c = _conn()
    rows = c.execute(sql_lite, params).fetchall()
    return [dict(r) for r in rows]


def _ex(sql_pg: str, sql_lite: str, params: tuple = ()) -> int:
    """Run DML — Postgres first, SQLite fallback. Returns rowcount."""
    if _USING_POSTGRES:
        return _pg.execute(sql_pg, params)
    c = _conn()
    cur = c.execute(sql_lite, params)
    c.commit()
    return cur.rowcount


def _insert(sql_pg: str, sql_lite: str, params: tuple = ()) -> int:
    """INSERT and return new row id."""
    if _USING_POSTGRES:
        return _pg.execute_returning(sql_pg, params)
    c = _conn()
    cur = c.execute(sql_lite, params)
    c.commit()
    return cur.lastrowid


def using_postgres() -> bool:
    return _USING_POSTGRES


# ── SQLite schema (only needed when Postgres is unavailable) ──────────────────

def migrate():
    if _USING_POSTGRES:
        return
    _conn().executescript("""
    CREATE TABLE IF NOT EXISTS habits (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL, habit_type TEXT NOT NULL,
        description TEXT, duration_min INTEGER, metadata TEXT
    );
    CREATE TABLE IF NOT EXISTS item_sightings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        object_class TEXT NOT NULL, zone_name TEXT NOT NULL,
        camera_id TEXT, confidence REAL,
        first_seen REAL NOT NULL, last_seen REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS emotion_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL, emotion TEXT NOT NULL,
        confidence REAL, source TEXT DEFAULT 'camera'
    );
    CREATE TABLE IF NOT EXISTS decisions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL, description TEXT NOT NULL,
        context TEXT, reversible INTEGER DEFAULT 1
    );
    CREATE TABLE IF NOT EXISTS goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at REAL NOT NULL, description TEXT NOT NULL,
        domain TEXT, target_date TEXT, completed INTEGER DEFAULT 0, notes TEXT
    );
    CREATE TABLE IF NOT EXISTS brain_state_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp REAL NOT NULL, state_json TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_habits_type   ON habits(habit_type, timestamp);
    CREATE INDEX IF NOT EXISTS idx_items_class   ON item_sightings(object_class, last_seen);
    CREATE INDEX IF NOT EXISTS idx_emotions_ts   ON emotion_log(timestamp);
    CREATE INDEX IF NOT EXISTS idx_brain_ts      ON brain_state_history(timestamp);
    """)


migrate()


# ── Habits ────────────────────────────────────────────────────────────────────

def log_habit(habit_type: str, description: str | None = None,
              duration_min: int | None = None, metadata: dict | None = None) -> int:
    meta = json.dumps(metadata) if metadata else None
    return _insert(
        "INSERT INTO habits (timestamp, habit_type, description, duration_min, metadata) VALUES (%s,%s,%s,%s,%s) RETURNING id",
        "INSERT INTO habits (timestamp, habit_type, description, duration_min, metadata) VALUES (?,?,?,?,?)",
        (time.time(), habit_type, description, duration_min, meta),
    )


def get_habit_pattern(habit_type: str, days: int = 30) -> list[dict]:
    since = time.time() - days * 86400
    return _sq(
        "SELECT * FROM habits WHERE habit_type=%s AND timestamp>%s ORDER BY timestamp DESC",
        "SELECT * FROM habits WHERE habit_type=? AND timestamp>? ORDER BY timestamp DESC",
        (habit_type, since),
    )


# ── Item locations ────────────────────────────────────────────────────────────

def upsert_item_sighting(object_class: str, zone_name: str,
                         camera_id: str | None = None, confidence: float = 1.0):
    now = time.time()
    if _USING_POSTGRES:
        _pg.execute(
            """INSERT INTO item_sightings (object_class, zone_name, camera_id, confidence, first_seen, last_seen)
               VALUES (%s,%s,%s,%s,%s,%s)
               ON CONFLICT (object_class, zone_name)
               DO UPDATE SET last_seen=%s, confidence=%s""",
            (object_class, zone_name, camera_id, confidence, now, now, now, confidence),
        )
    else:
        c = _conn()
        existing = c.execute(
            "SELECT id FROM item_sightings WHERE object_class=? AND zone_name=?",
            (object_class, zone_name),
        ).fetchone()
        if existing:
            c.execute("UPDATE item_sightings SET last_seen=?, confidence=? WHERE id=?",
                      (now, confidence, existing["id"]))
        else:
            c.execute(
                "INSERT INTO item_sightings (object_class, zone_name, camera_id, confidence, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                (object_class, zone_name, camera_id, confidence, now, now),
            )
        c.commit()


def find_item(object_class: str) -> dict | None:
    rows = _sq(
        "SELECT * FROM item_sightings WHERE object_class=%s ORDER BY last_seen DESC LIMIT 1",
        "SELECT * FROM item_sightings WHERE object_class=? ORDER BY last_seen DESC LIMIT 1",
        (object_class.lower(),),
    )
    return rows[0] if rows else None


def find_item_fuzzy(query: str) -> list[dict]:
    pat = f"%{query.lower()}%"
    return _sq(
        "SELECT * FROM item_sightings WHERE object_class LIKE %s ORDER BY last_seen DESC LIMIT 5",
        "SELECT * FROM item_sightings WHERE object_class LIKE ? ORDER BY last_seen DESC LIMIT 5",
        (pat,),
    )


# ── Emotions ──────────────────────────────────────────────────────────────────

def log_emotion(emotion: str, confidence: float = 1.0, source: str = "camera") -> int:
    return _insert(
        "INSERT INTO emotion_log (timestamp, emotion, confidence, source) VALUES (%s,%s,%s,%s) RETURNING id",
        "INSERT INTO emotion_log (timestamp, emotion, confidence, source) VALUES (?,?,?,?)",
        (time.time(), emotion, confidence, source),
    )


def get_emotion_trend(hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    return _sq(
        "SELECT * FROM emotion_log WHERE timestamp>%s ORDER BY timestamp",
        "SELECT * FROM emotion_log WHERE timestamp>? ORDER BY timestamp",
        (since,),
    )


# ── Decisions ─────────────────────────────────────────────────────────────────

def log_decision(description: str, context: str | None = None, reversible: bool = True) -> int:
    return _insert(
        "INSERT INTO decisions (timestamp, description, context, reversible) VALUES (%s,%s,%s,%s) RETURNING id",
        "INSERT INTO decisions (timestamp, description, context, reversible) VALUES (?,?,?,?)",
        (time.time(), description, context, int(reversible)),
    )


def get_decisions(days: int = 7) -> list[dict]:
    since = time.time() - days * 86400
    return _sq(
        "SELECT * FROM decisions WHERE timestamp>%s ORDER BY timestamp DESC",
        "SELECT * FROM decisions WHERE timestamp>? ORDER BY timestamp DESC",
        (since,),
    )


# ── Goals ─────────────────────────────────────────────────────────────────────

def add_goal(description: str, domain: str | None = None,
             target_date: str | None = None) -> int:
    return _insert(
        "INSERT INTO goals (created_at, description, domain, target_date) VALUES (%s,%s,%s,%s) RETURNING id",
        "INSERT INTO goals (created_at, description, domain, target_date) VALUES (?,?,?,?)",
        (time.time(), description, domain, target_date),
    )


def get_active_goals() -> list[dict]:
    return _sq(
        "SELECT * FROM goals WHERE completed=0 ORDER BY created_at DESC",
        "SELECT * FROM goals WHERE completed=0 ORDER BY created_at DESC",
    )


def complete_goal(goal_id: int) -> int:
    return _ex(
        "UPDATE goals SET completed=1 WHERE id=%s",
        "UPDATE goals SET completed=1 WHERE id=?",
        (goal_id,),
    )


def delete_goal(goal_id: int) -> int:
    return _ex(
        "DELETE FROM goals WHERE id=%s",
        "DELETE FROM goals WHERE id=?",
        (goal_id,),
    )


def delete_all_goals() -> int:
    return _ex("DELETE FROM goals", "DELETE FROM goals")


# ── Brain State history ───────────────────────────────────────────────────────

def snapshot_brain_state(state: dict):
    _insert(
        "INSERT INTO brain_state_history (timestamp, state_json) VALUES (%s,%s) RETURNING id",
        "INSERT INTO brain_state_history (timestamp, state_json) VALUES (?,?)",
        (time.time(), json.dumps(state)),
    )


def get_brain_state_history(hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    rows = _sq(
        "SELECT * FROM brain_state_history WHERE timestamp>%s ORDER BY timestamp",
        "SELECT * FROM brain_state_history WHERE timestamp>? ORDER BY timestamp",
        (since,),
    )
    for r in rows:
        r["state"] = json.loads(r.pop("state_json"))
    return rows
