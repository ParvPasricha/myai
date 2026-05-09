"""
Speech Improvement Analyzer.

Takes a transcript (text string) and returns metrics:
  - filler_words: count + list of instances
  - vocabulary_richness: type-token ratio (unique/total words)
  - rare_word_ratio: words not in common 3000-word list
  - avg_sentence_length: words per sentence
  - estimated_wpm: words per minute (requires duration_seconds)
  - sentiment: positive/negative/neutral + score
  - complexity_score: composite 0-10

All metrics are stored in the speech_sessions SQLite table.
Weekly aggregation available via get_weekly_report().
"""
import json
import re
import sqlite3
import string
import time
from pathlib import Path
from typing import Optional

import nltk
from textblob import TextBlob

_DB_PATH = Path(__file__).parent.parent / "memory" / "speech.db"
_DB_PATH.parent.mkdir(exist_ok=True)

# Filler words to track
_FILLERS = {
    "um", "uh", "umm", "uhh", "er", "erm",
    "like", "you know", "you know what i mean",
    "basically", "literally", "actually", "honestly",
    "right", "so", "well", "i mean", "kind of", "kinda",
    "sort of", "sorta", "anyway", "whatever", "stuff",
}

# Top ~3000 common English words (simplified — uses NLTK stopwords + frequency check)
_STOPWORDS: set[str] = set()
try:
    from nltk.corpus import stopwords
    _STOPWORDS = set(stopwords.words("english"))
except Exception:
    pass


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH, check_same_thread=False)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def _migrate():
    c = _conn()
    try:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS speech_sessions (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp        REAL NOT NULL,
            source           TEXT DEFAULT 'chat',
            transcript       TEXT NOT NULL,
            word_count       INTEGER,
            unique_words     INTEGER,
            filler_count     INTEGER,
            filler_rate      REAL,
            vocab_richness   REAL,
            rare_word_ratio  REAL,
            avg_sentence_len REAL,
            estimated_wpm    REAL,
            sentiment_score  REAL,
            sentiment_label  TEXT,
            complexity_score REAL,
            metrics_json     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_speech_ts ON speech_sessions(timestamp);
        """)
    finally:
        c.close()


_migrate()


# ── Analysis ──────────────────────────────────────────────────────────────────

def analyze(transcript: str, duration_seconds: Optional[float] = None,
            source: str = "chat") -> dict:
    """
    Analyze a transcript and store results.
    Returns full metrics dict.
    """
    if not transcript or not transcript.strip():
        return {}

    text = transcript.strip()

    # Tokenize
    try:
        sentences = nltk.sent_tokenize(text)
        words_raw = nltk.word_tokenize(text)
    except Exception:
        sentences = text.split(".")
        words_raw = text.split()

    words = [w.lower() for w in words_raw if w.isalpha()]
    word_count = len(words)
    if word_count == 0:
        return {}

    # Filler word detection
    text_lower = text.lower()
    filler_instances = []
    filler_count = 0
    for filler in _FILLERS:
        pattern = r"\b" + re.escape(filler) + r"\b"
        matches = re.findall(pattern, text_lower)
        if matches:
            filler_count += len(matches)
            filler_instances.extend([filler] * len(matches))

    filler_rate = round((filler_count / word_count) * 100, 2)

    # Vocabulary richness (type-token ratio)
    unique_words = len(set(words))
    vocab_richness = round(unique_words / word_count, 4)

    # Rare word ratio (words not in stopwords = potentially more sophisticated)
    content_words = [w for w in words if w not in _STOPWORDS and len(w) > 3]
    rare_word_ratio = round(len(content_words) / word_count, 4)

    # Average sentence length
    sentence_lengths = [len(nltk.word_tokenize(s)) for s in sentences if s.strip()]
    avg_sentence_len = round(sum(sentence_lengths) / len(sentence_lengths), 1) if sentence_lengths else 0

    # WPM (only if duration provided)
    estimated_wpm = None
    if duration_seconds and duration_seconds > 0:
        estimated_wpm = round((word_count / duration_seconds) * 60, 1)

    # Sentiment
    try:
        blob = TextBlob(text)
        sentiment_score = round(blob.sentiment.polarity, 4)
        if sentiment_score > 0.1:
            sentiment_label = "positive"
        elif sentiment_score < -0.1:
            sentiment_label = "negative"
        else:
            sentiment_label = "neutral"
    except Exception:
        sentiment_score = 0.0
        sentiment_label = "neutral"

    # Complexity score (0-10 composite)
    # High score = rich vocabulary, long sentences, few fillers, good pace
    vocab_score = min(vocab_richness * 10, 10)               # 0–10
    filler_penalty = min(filler_rate * 0.5, 5)               # up to -5
    sentence_score = min(avg_sentence_len / 2, 5)            # longer sentences → higher (capped at 5)
    complexity_score = round(max(0, vocab_score - filler_penalty + sentence_score / 2), 2)
    complexity_score = min(complexity_score, 10)

    metrics = {
        "word_count": word_count,
        "unique_words": unique_words,
        "filler_count": filler_count,
        "filler_rate": filler_rate,
        "filler_instances": list(set(filler_instances)),
        "vocab_richness": vocab_richness,
        "rare_word_ratio": rare_word_ratio,
        "avg_sentence_len": avg_sentence_len,
        "estimated_wpm": estimated_wpm,
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "complexity_score": complexity_score,
        "source": source,
        "timestamp": time.time(),
    }

    # Persist
    with _conn() as c:
        c.execute("""
            INSERT INTO speech_sessions
            (timestamp, source, transcript, word_count, unique_words,
             filler_count, filler_rate, vocab_richness, rare_word_ratio,
             avg_sentence_len, estimated_wpm, sentiment_score, sentiment_label,
             complexity_score, metrics_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            metrics["timestamp"], source, text[:2000], word_count, unique_words,
            filler_count, filler_rate, vocab_richness, rare_word_ratio,
            avg_sentence_len, estimated_wpm, sentiment_score, sentiment_label,
            complexity_score, json.dumps(metrics),
        ))

    return metrics


# ── Weekly report ─────────────────────────────────────────────────────────────

def _fetch_week(week_start: float, week_end: float) -> list[dict]:
    conn = _conn()
    try:
        rows = conn.execute(
            "SELECT * FROM speech_sessions WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp",
            (week_start, week_end),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _aggregate_sessions(sessions: list[dict]) -> dict:
    n = len(sessions)
    if n == 0:
        return {}
    avg_filler_rate = round(sum(s["filler_rate"] for s in sessions) / n, 2)
    avg_vocab = round(sum(s["vocab_richness"] for s in sessions) / n, 4)
    avg_complexity = round(sum(s["complexity_score"] for s in sessions) / n, 2)
    avg_sentence_len = round(
        sum(s["avg_sentence_len"] for s in sessions if s["avg_sentence_len"]) / n, 1
    )
    total_words = sum(s["word_count"] for s in sessions)
    wpm_sessions = [s["estimated_wpm"] for s in sessions if s["estimated_wpm"]]
    avg_wpm = round(sum(wpm_sessions) / len(wpm_sessions), 1) if wpm_sessions else None
    all_fillers: dict[str, int] = {}
    for s in sessions:
        metrics = json.loads(s["metrics_json"]) if s["metrics_json"] else {}
        for f in metrics.get("filler_instances", []):
            all_fillers[f] = all_fillers.get(f, 0) + 1
    top_fillers = sorted(all_fillers.items(), key=lambda x: -x[1])[:5]
    return {
        "sessions": n,
        "total_words": total_words,
        "avg_filler_rate": avg_filler_rate,
        "avg_vocab_richness": avg_vocab,
        "avg_complexity_score": avg_complexity,
        "avg_sentence_length": avg_sentence_len,
        "avg_wpm": avg_wpm,
        "top_fillers": [{"word": w, "count": c} for w, c in top_fillers],
        "sentiment_breakdown": {
            "positive": sum(1 for s in sessions if s["sentiment_label"] == "positive"),
            "neutral": sum(1 for s in sessions if s["sentiment_label"] == "neutral"),
            "negative": sum(1 for s in sessions if s["sentiment_label"] == "negative"),
        },
    }


def get_weekly_report(weeks_back: int = 0) -> dict:
    """Non-recursive: fetches current and previous week in two queries, no recursion."""
    now = time.time()
    this_start = now - (weeks_back + 1) * 7 * 86400
    this_end = now - weeks_back * 7 * 86400
    prev_start = this_start - 7 * 86400
    prev_end = this_start

    this_sessions = _fetch_week(this_start, this_end)
    prev_sessions = _fetch_week(prev_start, prev_end)

    if not this_sessions:
        return {"sessions": 0, "message": "No speech data for this period."}

    result = _aggregate_sessions(this_sessions)
    prev = _aggregate_sessions(prev_sessions)

    filler_delta = None
    if prev.get("avg_filler_rate") is not None and result.get("avg_filler_rate") is not None:
        filler_delta = round(result["avg_filler_rate"] - prev["avg_filler_rate"], 2)
    result["filler_rate_delta_vs_prev_week"] = filler_delta
    return result


def get_recent_sessions(limit: int = 20) -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM speech_sessions ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]
