"""
Conversation Logger — relationship and context memory.

When the AI detects a person's name in a transcript, it logs:
    {name, topic, sentiment, date, transcript_snippet}

This powers queries like:
    "When did I last talk to Rohan?"
    "What did I discuss with Priya?"
    "Who did I speak with this week?"

Person detection uses a simple NLP heuristic (NNP tags from NLTK POS tagger)
plus a small exclusion list of common non-person proper nouns.
LLM is used to extract the topic from the surrounding context.
"""
import json
import re
import sqlite3
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import nltk

_DB_PATH = Path(__file__).parent.parent / "memory" / "conversations.db"
_DB_PATH.parent.mkdir(exist_ok=True)

# Proper nouns that aren't person names — expand as needed
_NON_PERSON_NOUNS = {
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    "january", "february", "march", "april", "may", "june", "july",
    "august", "september", "october", "november", "december",
    "india", "delhi", "mumbai", "london", "new", "york", "google", "apple",
    "amazon", "youtube", "reddit", "twitter", "instagram", "whatsapp",
    "github", "python", "swift", "parv", "parvai",   # self-references
}


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _migrate():
    c = _conn()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS people_log (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        REAL NOT NULL,
            date             TEXT NOT NULL,
            person_name      TEXT NOT NULL,
            topic            TEXT,
            sentiment_label  TEXT,
            sentiment_score  REAL,
            snippet          TEXT,
            session_id       TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_people_name ON people_log(person_name, timestamp);
        CREATE INDEX IF NOT EXISTS idx_people_date ON people_log(date);
        """)
    finally:
        c.close()


_migrate()


# ── Person detection ──────────────────────────────────────────────────────────

def extract_people(text: str) -> list[str]:
    """
    Extract likely person names from text using POS tagging.
    Returns deduplicated list of names (title-cased).
    """
    if not text.strip():
        return []
    try:
        tokens = nltk.word_tokenize(text)
        tagged = nltk.pos_tag(tokens)
        people = []
        for word, tag in tagged:
            if (tag in ("NNP", "NNPS")
                    and word.lower() not in _NON_PERSON_NOUNS
                    and len(word) > 2
                    and word.isalpha()):
                people.append(word.title())
        return list(dict.fromkeys(people))   # deduplicate, preserve order
    except Exception:
        return []


def _extract_topic_heuristic(text: str) -> str:
    """Fast topic extraction without LLM — uses noun chunks."""
    try:
        tokens = nltk.word_tokenize(text.lower())
        tagged = nltk.pos_tag(tokens)
        from nltk.corpus import stopwords
        stops = set(stopwords.words("english"))
        nouns = [w for w, t in tagged if t.startswith("NN") and w not in stops and len(w) > 3]
        if nouns:
            freq: dict[str, int] = {}
            for n in nouns:
                freq[n] = freq.get(n, 0) + 1
            top = sorted(freq.items(), key=lambda x: -x[1])[:3]
            return ", ".join(w for w, _ in top)
    except Exception:
        pass
    return "general conversation"


# ── Logging ───────────────────────────────────────────────────────────────────

def log_conversation(
    text: str,
    sentiment_label: str = "neutral",
    sentiment_score: float = 0.0,
    session_id: Optional[str] = None,
) -> list[dict]:
    """
    Detect people in text, extract topic, and log each person interaction.
    Returns list of logged entries.
    """
    people = extract_people(text)
    if not people:
        return []

    topic = _extract_topic_heuristic(text)
    snippet = text[:200].replace("\n", " ")
    today = date.today().isoformat()
    now = time.time()
    logged = []

    with _conn() as c:
        for name in people:
            c.execute("""
                INSERT INTO people_log
                (timestamp, date, person_name, topic, sentiment_label,
                 sentiment_score, snippet, session_id)
                VALUES (?,?,?,?,?,?,?,?)
            """, (now, today, name, topic, sentiment_label,
                  sentiment_score, snippet, session_id))
            logged.append({"name": name, "topic": topic, "date": today})

    return logged


# ── Queries ───────────────────────────────────────────────────────────────────

def last_conversation(person_name: str) -> Optional[dict]:
    """When did I last talk to X?"""
    with _conn() as c:
        row = c.execute("""
            SELECT * FROM people_log
            WHERE LOWER(person_name) = LOWER(?)
            ORDER BY timestamp DESC LIMIT 1
        """, (person_name,)).fetchone()
    return dict(row) if row else None


def conversation_history(person_name: str, limit: int = 10) -> list[dict]:
    """All logged interactions with a person."""
    with _conn() as c:
        rows = c.execute("""
            SELECT * FROM people_log
            WHERE LOWER(person_name) = LOWER(?)
            ORDER BY timestamp DESC LIMIT ?
        """, (person_name, limit)).fetchall()
    return [dict(r) for r in rows]


def people_this_week() -> list[dict]:
    """Who did I interact with in the last 7 days?"""
    since = time.time() - 7 * 86400
    with _conn() as c:
        rows = c.execute("""
            SELECT person_name, COUNT(*) as mentions,
                   MAX(date) as last_date, MAX(topic) as last_topic
            FROM people_log
            WHERE timestamp > ?
            GROUP BY LOWER(person_name)
            ORDER BY mentions DESC
        """, (since,)).fetchall()
    return [dict(r) for r in rows]


def all_known_people(limit: int = 50) -> list[dict]:
    """All people ever mentioned, with last interaction date."""
    with _conn() as c:
        rows = c.execute("""
            SELECT person_name, COUNT(*) as mentions,
                   MAX(date) as last_date
            FROM people_log
            GROUP BY LOWER(person_name)
            ORDER BY last_date DESC
            LIMIT ?
        """, (limit,)).fetchall()
    return [dict(r) for r in rows]


def format_last_convo(person_name: str) -> str:
    """Human-readable string: 'Last talked to Rohan 3 days ago about the internship.'"""
    entry = last_conversation(person_name)
    if not entry:
        return f"No recorded conversations with {person_name}."
    days_ago = (date.today() - date.fromisoformat(entry["date"])).days
    when = "today" if days_ago == 0 else f"{days_ago} day{'s' if days_ago != 1 else ''} ago"
    topic = entry.get("topic", "something")
    return f"Last talked to {person_name} {when}, about: {topic}."
