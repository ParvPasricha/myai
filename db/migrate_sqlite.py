"""
One-time migration: SQLite structured.db → PostgreSQL.

Run once:
    cd ~/Desktop/myai && .venv/bin/python3 -m db.migrate_sqlite

Safe to run again — uses INSERT … ON CONFLICT DO NOTHING so it
won't duplicate rows. Reports counts before and after.

Tables migrated:
    goals, decisions, habits, emotion_log,
    item_sightings, brain_state_history

NOT migrated (stay on SQLite — single-process, high-write):
    research.db     → topics, quiz_sessions, research_log
    episodic.db     → conversation turns
    speech.db       → speech analysis
    intelligence.db → unified memory decisions
    faces.db        → face recognition
"""
import sqlite3
from pathlib import Path

from db import postgres as pg

_SQLITE_PATH = Path(__file__).parent.parent / "memory" / "structured.db"


def _sqlite() -> sqlite3.Connection:
    c = sqlite3.connect(str(_SQLITE_PATH), check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _migrate_goals(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM goals").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO goals (id, created_at, description, domain, target_date, completed, notes)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO NOTHING""",
        [(r["id"], r["created_at"], r["description"], r["domain"],
          r["target_date"], r["completed"], r["notes"]) for r in rows],
    )
    # Reset serial so next INSERT gets the right id
    pg.execute("SELECT setval('goals_id_seq', COALESCE((SELECT MAX(id) FROM goals), 1))")
    return len(rows)


def _migrate_decisions(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM decisions").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO decisions (id, timestamp, description, context, reversible)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (id) DO NOTHING""",
        [(r["id"], r["timestamp"], r["description"], r["context"], r["reversible"])
         for r in rows],
    )
    pg.execute("SELECT setval('decisions_id_seq', COALESCE((SELECT MAX(id) FROM decisions), 1))")
    return len(rows)


def _migrate_habits(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM habits").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO habits (id, timestamp, habit_type, description, duration_min, metadata)
           VALUES (%s, %s, %s, %s, %s, %s)
           ON CONFLICT (id) DO NOTHING""",
        [(r["id"], r["timestamp"], r["habit_type"], r["description"],
          r["duration_min"], r["metadata"]) for r in rows],
    )
    pg.execute("SELECT setval('habits_id_seq', COALESCE((SELECT MAX(id) FROM habits), 1))")
    return len(rows)


def _migrate_emotions(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM emotion_log").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO emotion_log (id, timestamp, emotion, confidence, source)
           VALUES (%s, %s, %s, %s, %s)
           ON CONFLICT (id) DO NOTHING""",
        [(r["id"], r["timestamp"], r["emotion"], r["confidence"], r["source"])
         for r in rows],
    )
    pg.execute("SELECT setval('emotion_log_id_seq', COALESCE((SELECT MAX(id) FROM emotion_log), 1))")
    return len(rows)


def _migrate_items(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM item_sightings").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO item_sightings
               (id, object_class, zone_name, camera_id, confidence, first_seen, last_seen)
           VALUES (%s, %s, %s, %s, %s, %s, %s)
           ON CONFLICT (object_class, zone_name) DO UPDATE
               SET last_seen = EXCLUDED.last_seen,
                   confidence = EXCLUDED.confidence""",
        [(r["id"], r["object_class"], r["zone_name"], r["camera_id"],
          r["confidence"], r["first_seen"], r["last_seen"]) for r in rows],
    )
    pg.execute("SELECT setval('item_sightings_id_seq', COALESCE((SELECT MAX(id) FROM item_sightings), 1))")
    return len(rows)


def _migrate_brain_state(src: sqlite3.Connection) -> int:
    rows = src.execute("SELECT * FROM brain_state_history").fetchall()
    if not rows:
        return 0
    pg.executemany(
        """INSERT INTO brain_state_history (id, timestamp, state_json)
           VALUES (%s, %s, %s)
           ON CONFLICT (id) DO NOTHING""",
        [(r["id"], r["timestamp"], r["state_json"]) for r in rows],
    )
    pg.execute("SELECT setval('brain_state_history_id_seq', COALESCE((SELECT MAX(id) FROM brain_state_history), 1))")
    return len(rows)


def run() -> None:
    print("PARV-AI: SQLite → PostgreSQL migration")
    print(f"Source: {_SQLITE_PATH}")
    print()

    if not _SQLITE_PATH.exists():
        print("ERROR: structured.db not found")
        return

    print("Ensuring Postgres schema …")
    pg.migrate()

    src = _sqlite()
    steps = [
        ("goals",               _migrate_goals),
        ("decisions",           _migrate_decisions),
        ("habits",              _migrate_habits),
        ("emotion_log",         _migrate_emotions),
        ("item_sightings",      _migrate_items),
        ("brain_state_history", _migrate_brain_state),
    ]

    total = 0
    for name, fn in steps:
        try:
            n = fn(src)
            print(f"  {name:25s} {n:>6} rows migrated")
            total += n
        except Exception as e:
            print(f"  {name:25s} ERROR: {e}")

    src.close()
    print(f"\nDone. {total} rows total.")
    print("structured.db stays in place as read-only backup.")
    print("Set DATABASE_URL in .env to point future writes to Postgres.")


if __name__ == "__main__":
    run()
