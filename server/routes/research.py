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


# ── Personalised suggestions ───────────────────────────────────────────────────

@router.get("/research/suggestions")
async def topic_suggestions(_auth: dict = Depends(require_auth)):
    """
    5 personalised topic suggestions built from unified memory + quiz history.
    Mix of: revisit weak areas, deepen known domains, explore new territory.
    """
    import json as _json
    from intelligence.learning_engine import get_domain_summary
    from research.db import get_weak_areas, get_recent_topics

    domain_counts = await asyncio.to_thread(get_domain_summary)
    weak         = get_weak_areas(3)
    recent       = [r["topic"] for r in get_recent_topics(7)]
    domains      = get_active_domains()
    top_domains  = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:4]

    system = "Return ONLY valid JSON. No markdown."
    prompt = (
        f"User's top interest domains (from AI memory): {[d for d, _ in top_domains]}.\n"
        f"Active research domains: {domains}.\n"
        f"Recent topics (avoid repeating): {recent}.\n"
        f"Weak quiz areas to revisit: {[w['topic'] for w in weak]}.\n\n"
        "Generate 6 topic suggestions. Mix: 2 that deepen known strengths, "
        "2 that revisit weak areas, 2 that explore completely new territory.\n"
        '{"suggestions": [{'
        '"topic": "specific topic name", '
        '"description": "1 sentence on why this matters to them", '
        '"domain": "code|physics|maths|business|editing|personal", '
        '"type": "deepen|revisit|explore"'
        "}]}"
    )

    try:
        raw = await llm.complete(prompt=prompt, system=system, max_tokens=600)
        text = raw["text"].strip().lstrip("```json").lstrip("```").rstrip("```")
        data = _json.loads(text[text.find("{"):text.rfind("}") + 1])
        suggestions = data.get("suggestions", [])[:6]
    except Exception as e:
        log.warn("suggestions_failed", error=str(e))
        suggestions = [
            {"topic": d, "description": f"Deepen your {d} knowledge",
             "domain": d, "type": "deepen"}
            for d in (domains or ["code", "maths"])[:6]
        ]

    return {"suggestions": suggestions}


class CustomTopicBody(BaseModel):
    topic: str

@router.post("/research/topic/custom")
async def set_custom_topic(body: CustomTopicBody, _auth: dict = Depends(require_auth)):
    """Set a custom research topic for today, overriding the AI-generated one."""
    today = date.today().isoformat()
    system = "Return ONLY valid JSON. No markdown."
    prompt = (
        f"Write a focused 3-sentence research brief for the topic: '{body.topic}'.\n"
        '{"description": "...", "domains": ["primary", "optional secondary"]}'
    )
    try:
        raw = await llm.complete(prompt=prompt, system=system, max_tokens=200)
        text = raw["text"].strip()
        data = _json.loads(text[text.find("{"):text.rfind("}") + 1])
        desc    = data.get("description", f"Research everything about {body.topic}.")
        domains = data.get("domains", ["general"])
    except Exception:
        desc    = f"Deep research on: {body.topic}."
        domains = ["general"]

    from research.db import save_topic, _conn
    with _conn() as c:
        c.execute("DELETE FROM topics WHERE date = ?", (today,))
    save_topic(date=today, topic=body.topic, description=desc,
               domains=domains, ts=time.time())
    topic = get_today_topic(today)
    import json as _json2
    return {**topic, "domains": _json2.loads(topic["domains"])}


import asyncio
