"""
Research + Quiz routes:

    GET  /research/today          — today's topic (generates if missing)
    POST /research/log            — log a research entry (browser/voice/manual)
    GET  /research/log/{date}     — get research log for a date
    GET  /research/quiz           — get today's quiz (generates if missing)
    POST /research/quiz/{id}      — submit quiz answers
    GET  /research/leaderboard    — recent scores
    GET  /research/domains        — list interest domains
    POST /research/domains        — add a domain
    DELETE /research/domains/{d}  — remove a domain
    POST /research/topic/refresh  — force-regenerate today's topic
"""
import time
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from server.auth import require_auth
from research.db import (
    migrate, get_today_topic, get_recent_topics, log_research,
    get_research_log, get_leaderboard, get_streak, get_active_domains,
)
from research.topic_generator import generate_today_topic
from research.quiz_engine import generate_quiz, evaluate_quiz
from observability.logger import log

router = APIRouter()

# Ensure schema exists when this module is imported
migrate()


# ── Topic ──────────────────────────────────────────────────────────────────────

@router.get("/research/today")
async def today_topic(_auth: dict = Depends(require_auth)):
    today = date.today().isoformat()
    topic = await generate_today_topic()
    import json
    return {**topic, "domains": json.loads(topic["domains"])}


@router.post("/research/topic/refresh")
async def refresh_topic(_auth: dict = Depends(require_auth)):
    topic = await generate_today_topic(force=True)
    import json
    return {**topic, "domains": json.loads(topic["domains"])}


# ── Research Log ───────────────────────────────────────────────────────────────

class LogEntry(BaseModel):
    title: str | None = None
    summary: str | None = None
    url: str | None = None
    source: str = "manual"   # manual | browser | voice

@router.post("/research/log")
async def add_log(entry: LogEntry, _auth: dict = Depends(require_auth)):
    today = date.today().isoformat()
    topic = get_today_topic(today)
    if not topic:
        raise HTTPException(status_code=404, detail="No topic for today — call /research/today first")
    entry_id = log_research(
        topic_id=topic["id"],
        source=entry.source,
        title=entry.title,
        summary=entry.summary,
        url=entry.url,
        ts=time.time(),
    )
    log.info("research_logged", topic=topic["topic"], source=entry.source)
    return {"ok": True, "id": entry_id}


@router.get("/research/log/{for_date}")
async def get_log(for_date: str, _auth: dict = Depends(require_auth)):
    topic = get_today_topic(for_date)
    if not topic:
        return {"entries": [], "topic": None}
    entries = get_research_log(topic["id"])
    return {"topic": topic["topic"], "entries": entries}


# ── Quiz ───────────────────────────────────────────────────────────────────────

@router.get("/research/quiz")
async def get_quiz(_auth: dict = Depends(require_auth)):
    today = date.today().isoformat()
    topic = get_today_topic(today)
    if not topic:
        raise HTTPException(status_code=404, detail="No topic today — call /research/today first")
    quiz = await generate_quiz(topic)
    return quiz


class QuizSubmission(BaseModel):
    answers: list[str]   # ["A", "C", "B", ...] one per question

@router.post("/research/quiz/{quiz_id}")
async def submit_quiz(quiz_id: int, body: QuizSubmission, _auth: dict = Depends(require_auth)):
    try:
        result = await evaluate_quiz(quiz_id, body.answers)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Publish to MQTT
    from server.main import mqtt_publish
    mqtt_publish("parv/quiz/completed", f"score:{result['score']}")
    return result


# ── Leaderboard + Stats ────────────────────────────────────────────────────────

@router.get("/research/leaderboard")
async def leaderboard(_auth: dict = Depends(require_auth)):
    scores = get_leaderboard(20)
    return {
        "streak": get_streak(),
        "scores": scores,
    }


# ── Domains ───────────────────────────────────────────────────────────────────

@router.get("/research/domains")
async def list_domains(_auth: dict = Depends(require_auth)):
    return {"domains": get_active_domains()}


class DomainBody(BaseModel):
    domain: str

@router.post("/research/domains")
async def add_domain(body: DomainBody, _auth: dict = Depends(require_auth)):
    from research.db import _conn
    with _conn() as c:
        c.execute("INSERT OR IGNORE INTO user_domains (domain, active) VALUES (?, 1)", (body.domain,))
        c.execute("UPDATE user_domains SET active = 1 WHERE domain = ?", (body.domain,))
    return {"ok": True}


@router.delete("/research/domains/{domain}")
async def remove_domain(domain: str, _auth: dict = Depends(require_auth)):
    from research.db import _conn
    with _conn() as c:
        c.execute("UPDATE user_domains SET active = 0 WHERE domain = ?", (domain,))
    return {"ok": True}
