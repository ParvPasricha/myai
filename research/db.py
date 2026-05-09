"""
SQLite database for the research + quiz system.

Tables:
    user_domains     — interest areas the AI picks topics from
    topics           — daily topic assignments
    research_log     — things the user read/noted during the day
    quiz_sessions    — quiz attempts with score + per-question breakdown
"""
import json
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).parent.parent / "memory" / "research.db"
_DB_PATH.parent.mkdir(exist_ok=True)


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def migrate():
    with _conn() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS user_domains (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            domain  TEXT NOT NULL UNIQUE,
            active  INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS topics (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            date         TEXT NOT NULL UNIQUE,   -- YYYY-MM-DD
            topic        TEXT NOT NULL,
            description  TEXT NOT NULL,
            domains      TEXT NOT NULL DEFAULT '[]',  -- JSON list
            generated_at REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS research_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id    INTEGER REFERENCES topics(id),
            source      TEXT NOT NULL DEFAULT 'manual',  -- manual/browser/voice
            title       TEXT,
            summary     TEXT,
            url         TEXT,
            logged_at   REAL NOT NULL
        );

        CREATE TABLE IF NOT EXISTS quiz_sessions (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id      INTEGER NOT NULL REFERENCES topics(id),
            date          TEXT NOT NULL,
            questions     TEXT NOT NULL,   -- JSON
            user_answers  TEXT,            -- JSON, null until submitted
            score         REAL,            -- 0-100, null until submitted
            breakdown     TEXT,            -- JSON per-question result
            completed_at  REAL,
            created_at    REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_topics_date ON topics(date);
        CREATE INDEX IF NOT EXISTS idx_quiz_topic  ON quiz_sessions(topic_id);
        """)

    # Seed default domains if empty
    with _conn() as c:
        if c.execute("SELECT COUNT(*) FROM user_domains").fetchone()[0] == 0:
            default_domains = [
                "Computer Science", "Mathematics", "Physics",
                "Machine Learning", "History", "Philosophy",
                "Economics", "Biology", "Psychology",
            ]
            c.executemany(
                "INSERT OR IGNORE INTO user_domains (domain) VALUES (?)",
                [(d,) for d in default_domains],
            )


# ── Query helpers ─────────────────────────────────────────────────────────────

def get_today_topic(date: str) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM topics WHERE date = ?", (date,)).fetchone()
        return dict(row) if row else None


def save_topic(date: str, topic: str, description: str, domains: list[str], ts: float) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT OR REPLACE INTO topics (date, topic, description, domains, generated_at) VALUES (?,?,?,?,?)",
            (date, topic, description, json.dumps(domains), ts),
        )
        return cur.lastrowid


def get_recent_topics(n: int = 14) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM topics ORDER BY date DESC LIMIT ?", (n,)
        ).fetchall()
        return [dict(r) for r in rows]


def get_weak_areas(limit: int = 5) -> list[dict]:
    """Topics with the lowest quiz scores (needs improvement)."""
    with _conn() as c:
        rows = c.execute("""
            SELECT t.topic, t.domains, AVG(q.score) as avg_score, COUNT(q.id) as attempts
            FROM quiz_sessions q
            JOIN topics t ON t.id = q.topic_id
            WHERE q.score IS NOT NULL
            GROUP BY t.topic
            ORDER BY avg_score ASC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_active_domains() -> list[str]:
    with _conn() as c:
        rows = c.execute("SELECT domain FROM user_domains WHERE active = 1").fetchall()
        return [r["domain"] for r in rows]


def log_research(topic_id: int, source: str, title: str | None, summary: str | None,
                 url: str | None, ts: float) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO research_log (topic_id, source, title, summary, url, logged_at) VALUES (?,?,?,?,?,?)",
            (topic_id, source, title, summary, url, ts),
        )
        return cur.lastrowid


def get_research_log(topic_id: int) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM research_log WHERE topic_id = ? ORDER BY logged_at DESC", (topic_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def save_quiz(topic_id: int, date: str, questions: list, ts: float) -> int:
    with _conn() as c:
        cur = c.execute(
            "INSERT INTO quiz_sessions (topic_id, date, questions, created_at) VALUES (?,?,?,?)",
            (topic_id, date, json.dumps(questions), ts),
        )
        return cur.lastrowid


def submit_quiz(quiz_id: int, answers: list, score: float,
                breakdown: list, completed_at: float):
    with _conn() as c:
        c.execute(
            "UPDATE quiz_sessions SET user_answers=?, score=?, breakdown=?, completed_at=? WHERE id=?",
            (json.dumps(answers), score, json.dumps(breakdown), completed_at, quiz_id),
        )


def get_quiz(quiz_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute("SELECT * FROM quiz_sessions WHERE id = ?", (quiz_id,)).fetchone()
        return dict(row) if row else None


def get_quiz_for_topic(topic_id: int) -> dict | None:
    with _conn() as c:
        row = c.execute(
            "SELECT * FROM quiz_sessions WHERE topic_id = ? ORDER BY created_at DESC LIMIT 1",
            (topic_id,),
        ).fetchone()
        return dict(row) if row else None


def get_leaderboard(limit: int = 10) -> list[dict]:
    with _conn() as c:
        rows = c.execute("""
            SELECT t.date, t.topic, q.score, q.completed_at
            FROM quiz_sessions q
            JOIN topics t ON t.id = q.topic_id
            WHERE q.score IS NOT NULL
            ORDER BY q.completed_at DESC
            LIMIT ?
        """, (limit,)).fetchall()
        return [dict(r) for r in rows]


def get_streak() -> int:
    """Count consecutive days with a completed quiz ending today."""
    with _conn() as c:
        rows = c.execute("""
            SELECT DISTINCT date FROM quiz_sessions
            WHERE score IS NOT NULL
            ORDER BY date DESC
        """).fetchall()
    from datetime import date, timedelta
    dates = {r["date"] for r in rows}
    streak = 0
    day = date.today()
    while day.isoformat() in dates:
        streak += 1
        day -= timedelta(days=1)
    return streak
