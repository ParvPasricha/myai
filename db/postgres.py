"""
PostgreSQL connection pool for PARV-AI.

Usage:
    from db.postgres import query, execute, executemany

All functions are thread-safe and work from sync or async contexts
(call via asyncio.to_thread when inside an async function).

Schema is defined here — call migrate() once on startup.
Tables currently here: goals, decisions, habits, emotion_log,
                       item_sightings, brain_state_history.
Research/episodic/speech stay on SQLite (single-process, high-write).
"""
import json
import os
import time
from contextlib import contextmanager
from typing import Any

import psycopg2
import psycopg2.extras
import psycopg2.pool

# ── Connection string ─────────────────────────────────────────────────────────

def _dsn() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url:
        return url
    user = os.environ.get("USER", "postgres")
    host = os.environ.get("PG_HOST", "localhost")
    port = os.environ.get("PG_PORT", "5432")
    db   = os.environ.get("PG_DB",   "parvai")
    return f"postgresql://{user}@{host}:{port}/{db}"


# Thread-safe pool — min 1, max 10 connections
_pool: psycopg2.pool.ThreadedConnectionPool | None = None


def _get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(1, 10, _dsn())
    return _pool


@contextmanager
def _conn():
    pool = _get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


# ── Public helpers ────────────────────────────────────────────────────────────

def query(sql: str, params: tuple = ()) -> list[dict]:
    with _conn() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]


def query_one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int:
    """Run a DML statement, return rowcount."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.rowcount


def execute_returning(sql: str, params: tuple = ()) -> Any:
    """Run INSERT … RETURNING id, return the value."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
            return row[0] if row else None


def executemany(sql: str, param_list: list[tuple]) -> None:
    with _conn() as conn:
        with conn.cursor() as cur:
            psycopg2.extras.execute_batch(cur, sql, param_list)


def ping() -> bool:
    try:
        query("SELECT 1")
        return True
    except Exception:
        return False


# ── Schema ────────────────────────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id          SERIAL PRIMARY KEY,
    created_at  DOUBLE PRECISION NOT NULL,
    description TEXT NOT NULL,
    domain      TEXT,
    target_date TEXT,
    completed   INTEGER NOT NULL DEFAULT 0,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS decisions (
    id          SERIAL PRIMARY KEY,
    timestamp   DOUBLE PRECISION NOT NULL,
    description TEXT NOT NULL,
    context     TEXT,
    reversible  INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS habits (
    id           SERIAL PRIMARY KEY,
    timestamp    DOUBLE PRECISION NOT NULL,
    habit_type   TEXT NOT NULL,
    description  TEXT,
    duration_min INTEGER,
    metadata     TEXT
);

CREATE TABLE IF NOT EXISTS emotion_log (
    id          SERIAL PRIMARY KEY,
    timestamp   DOUBLE PRECISION NOT NULL,
    emotion     TEXT NOT NULL,
    confidence  DOUBLE PRECISION,
    source      TEXT NOT NULL DEFAULT 'camera'
);

CREATE TABLE IF NOT EXISTS item_sightings (
    id           SERIAL PRIMARY KEY,
    object_class TEXT NOT NULL,
    zone_name    TEXT NOT NULL,
    camera_id    TEXT,
    confidence   DOUBLE PRECISION,
    first_seen   DOUBLE PRECISION NOT NULL,
    last_seen    DOUBLE PRECISION NOT NULL,
    UNIQUE (object_class, zone_name)
);

CREATE TABLE IF NOT EXISTS brain_state_history (
    id         SERIAL PRIMARY KEY,
    timestamp  DOUBLE PRECISION NOT NULL,
    state_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_goals_completed   ON goals(completed);
CREATE INDEX IF NOT EXISTS idx_decisions_ts      ON decisions(timestamp);
CREATE INDEX IF NOT EXISTS idx_habits_type_ts    ON habits(habit_type, timestamp);
CREATE INDEX IF NOT EXISTS idx_emotions_ts       ON emotion_log(timestamp);
CREATE INDEX IF NOT EXISTS idx_brain_ts          ON brain_state_history(timestamp);
CREATE INDEX IF NOT EXISTS idx_items_class       ON item_sightings(object_class, last_seen);
"""


def migrate() -> None:
    """Create all tables if they don't exist. Safe to call on every startup."""
    with _conn() as conn:
        with conn.cursor() as cur:
            cur.execute(_SCHEMA)
