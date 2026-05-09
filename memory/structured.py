"""
Structured memory — Layer 4.

Stores typed, queryable facts: habits, item locations, emotion logs,
decisions, goals, and Brain State history.

Uses SQLite now (dev). Schema is PostgreSQL-compatible for Pi migration —
just swap the connection string in Phase 10.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent.parent / "memory" / "structured.db"
_DB_PATH.parent.mkdir(exist_ok=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate():
    with _conn() as c:
        c.executescript("""
        -- Habit tracking: repeated behaviours with timestamps
        CREATE TABLE IF NOT EXISTS habits (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            habit_type  TEXT NOT NULL,   -- sleep, exercise, work, meal, etc.
            description TEXT,
            duration_min INTEGER,
            metadata    TEXT             -- JSON
        );

        -- Item location memory (populated by vision pipeline in Phase 7)
        CREATE TABLE IF NOT EXISTS item_sightings (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            object_class TEXT NOT NULL,  -- keys, wallet, headphones, etc.
            zone_name    TEXT NOT NULL,  -- desk, shelf, couch, etc.
            camera_id    TEXT,
            confidence   REAL,
            first_seen   REAL NOT NULL,
            last_seen    REAL NOT NULL
        );

        -- Emotion log (populated by vision pipeline in Phase 7)
        CREATE TABLE IF NOT EXISTS emotion_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            emotion     TEXT NOT NULL,   -- happy, sad, focused, tired, etc.
            confidence  REAL,
            source      TEXT DEFAULT 'camera'  -- camera | voice | self_report
        );

        -- Decisions: things the user decided or stated
        CREATE TABLE IF NOT EXISTS decisions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            description TEXT NOT NULL,
            context     TEXT,
            reversible  INTEGER DEFAULT 1
        );

        -- Goals: long-term objectives stated by user
        CREATE TABLE IF NOT EXISTS goals (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at  REAL NOT NULL,
            description TEXT NOT NULL,
            domain      TEXT,
            target_date TEXT,
            completed   INTEGER DEFAULT 0,
            notes       TEXT
        );

        -- Brain State snapshots (historical)
        CREATE TABLE IF NOT EXISTS brain_state_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   REAL NOT NULL,
            state_json  TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_habits_type      ON habits(habit_type, timestamp);
        CREATE INDEX IF NOT EXISTS idx_items_class      ON item_sightings(object_class, last_seen);
        CREATE INDEX IF NOT EXISTS idx_emotions_ts      ON emotion_log(timestamp);
        CREATE INDEX IF NOT EXISTS idx_brain_ts         ON brain_state_history(timestamp);
        """)


# ── Habits ────────────────────────────────────────────────────────────────────

def log_habit(habit_type: str, description: str | None = None,
              duration_min: int | None = None, metadata: dict | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO habits (timestamp, habit_type, description, duration_min, metadata) VALUES (?,?,?,?,?)",
            (time.time(), habit_type, description, duration_min,
             json.dumps(metadata) if metadata else None),
        )
        return cur.lastrowid


def get_habit_pattern(habit_type: str, days: int = 30) -> list[dict]:
    since = time.time() - days * 86400
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM habits WHERE habit_type = ? AND timestamp > ? ORDER BY timestamp DESC",
            (habit_type, since),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Item locations ────────────────────────────────────────────────────────────

def upsert_item_sighting(object_class: str, zone_name: str,
                         camera_id: str | None = None, confidence: float = 1.0):
    now = time.time()
    with _conn() as c:
        existing = c.execute(
            "SELECT id FROM item_sightings WHERE object_class = ? AND zone_name = ?",
            (object_class, zone_name),
        ).fetchone()
        if existing:
            c.execute(
                "UPDATE item_sightings SET last_seen = ?, confidence = ? WHERE id = ?",
                (now, confidence, existing["id"]),
            )
        else:
            c.execute(
                "INSERT INTO item_sightings (object_class, zone_name, camera_id, confidence, first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                (object_class, zone_name, camera_id, confidence, now, now),
            )


def find_item(object_class: str) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM item_sightings WHERE object_class = ? ORDER BY last_seen DESC LIMIT 1",
            (object_class.lower(),),
        ).fetchone()
        return dict(row) if row else None


def find_item_fuzzy(query: str) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM item_sightings WHERE object_class LIKE ? ORDER BY last_seen DESC LIMIT 5",
            (f"%{query.lower()}%",),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Emotions ─────────────────────────────────────────────────────────────────

def log_emotion(emotion: str, confidence: float = 1.0, source: str = "camera") -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO emotion_log (timestamp, emotion, confidence, source) VALUES (?,?,?,?)",
            (time.time(), emotion, confidence, source),
        )
        return cur.lastrowid


def get_emotion_trend(hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM emotion_log WHERE timestamp > ? ORDER BY timestamp",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Decisions ─────────────────────────────────────────────────────────────────

def log_decision(description: str, context: str | None = None, reversible: bool = True) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO decisions (timestamp, description, context, reversible) VALUES (?,?,?,?)",
            (time.time(), description, context, int(reversible)),
        )
        return cur.lastrowid


def get_decisions(days: int = 7) -> list[dict]:
    since = time.time() - days * 86400
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM decisions WHERE timestamp > ? ORDER BY timestamp DESC",
            (since,),
        ).fetchall()
        return [dict(r) for r in rows]


# ── Goals ─────────────────────────────────────────────────────────────────────

def add_goal(description: str, domain: str | None = None,
             target_date: str | None = None) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO goals (created_at, description, domain, target_date) VALUES (?,?,?,?)",
            (time.time(), description, domain, target_date),
        )
        return cur.lastrowid


def get_active_goals() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM goals WHERE completed = 0 ORDER BY created_at DESC",
        ).fetchall()
        return [dict(r) for r in rows]


# ── Brain State history ───────────────────────────────────────────────────────

def snapshot_brain_state(state: dict):
    with _conn() as c:
        c.execute(
            "INSERT INTO brain_state_history (timestamp, state_json) VALUES (?,?)",
            (time.time(), json.dumps(state)),
        )


def get_brain_state_history(hours: int = 24) -> list[dict]:
    since = time.time() - hours * 3600
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM brain_state_history WHERE timestamp > ? ORDER BY timestamp",
            (since,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["state"] = json.loads(d.pop("state_json"))
            result.append(d)
        return result


migrate()
