"""
Speech Improvement routes:

    POST /speech/analyze          — analyze a transcript, get metrics back
    GET  /speech/report           — weekly speech metrics report
    GET  /speech/report/previous  — previous week comparison
    GET  /speech/sessions         — recent session list
    GET  /speech/people           — all known people from conversations
    GET  /speech/person/{name}    — last conversation + history for a person
    GET  /speech/last/{name}      — quick: "when did I last talk to X?"
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from typing import Optional

from server.auth import require_auth
from intelligence.speech_analyzer import analyze, get_weekly_report, get_recent_sessions
from intelligence.conversation_logger import (
    log_conversation, last_conversation, conversation_history,
    people_this_week, all_known_people, format_last_convo,
)
from observability.logger import log

router = APIRouter()


# ── Analysis ──────────────────────────────────────────────────────────────────

class AnalyzeBody(BaseModel):
    transcript: str
    duration_seconds: Optional[float] = None
    source: str = "manual"           # chat | voice | manual
    session_id: Optional[str] = None

@router.post("/speech/analyze")
async def analyze_speech(body: AnalyzeBody, _auth: dict = Depends(require_auth)):
    if not body.transcript.strip():
        return {"error": "transcript is empty"}

    # Analyze metrics
    metrics = analyze(
        transcript=body.transcript,
        duration_seconds=body.duration_seconds,
        source=body.source,
    )

    # Log people mentioned
    people_logged = log_conversation(
        text=body.transcript,
        sentiment_label=metrics.get("sentiment_label", "neutral"),
        sentiment_score=metrics.get("sentiment_score", 0.0),
        session_id=body.session_id,
    )

    # Publish to MQTT
    try:
        from server.main import mqtt_publish
        import json
        mqtt_publish("parv/speech/analyzed", json.dumps({
            "filler_rate": metrics.get("filler_rate"),
            "vocab_richness": metrics.get("vocab_richness"),
            "complexity_score": metrics.get("complexity_score"),
            "sentiment": metrics.get("sentiment_label"),
        }))
    except Exception:
        pass

    log.info("speech_analyzed",
             word_count=metrics.get("word_count"),
             filler_rate=metrics.get("filler_rate"),
             complexity=metrics.get("complexity_score"),
             people=len(people_logged))

    return {
        "metrics": metrics,
        "people_mentioned": people_logged,
        "tip": _generate_tip(metrics),
    }


def _generate_tip(metrics: dict) -> str:
    filler_rate = metrics.get("filler_rate", 0)
    complexity = metrics.get("complexity_score", 5)
    vocab = metrics.get("vocab_richness", 0.5)
    wpm = metrics.get("estimated_wpm")

    if filler_rate > 5:
        top = metrics.get("filler_instances", [])
        worst = max(set(top), key=top.count) if top else "filler words"
        return f"High filler rate ({filler_rate:.1f}/100 words). Most used: '{worst}'. Try pausing silently instead."
    if vocab < 0.4:
        return "Vocabulary richness is low — try varying your word choice more."
    if wpm and wpm > 180:
        return f"Speaking fast at {wpm:.0f} WPM. Aim for 130–150 WPM for clarity."
    if wpm and wpm < 100:
        return f"Speaking slowly at {wpm:.0f} WPM. Try to be more concise."
    if complexity > 7:
        return f"Strong speech! Complexity score {complexity:.1f}/10. Keep it up."
    return f"Solid session. Complexity {complexity:.1f}/10, filler rate {filler_rate:.1f}/100 words."


# ── Reports ───────────────────────────────────────────────────────────────────

@router.get("/speech/report")
async def weekly_report(_auth: dict = Depends(require_auth)):
    report = get_weekly_report(weeks_back=0)
    prev = get_weekly_report(weeks_back=1)
    return {
        "this_week": report,
        "last_week": prev,
        "improvement": _compute_improvement(report, prev),
    }


@router.get("/speech/report/previous")
async def previous_report(_auth: dict = Depends(require_auth)):
    return get_weekly_report(weeks_back=1)


def _compute_improvement(current: dict, previous: dict) -> dict:
    if not current.get("sessions") or not previous.get("sessions"):
        return {}
    filler_change = None
    if current.get("avg_filler_rate") is not None and previous.get("avg_filler_rate") is not None:
        delta = current["avg_filler_rate"] - previous["avg_filler_rate"]
        filler_change = {"delta": round(delta, 2), "direction": "worse" if delta > 0 else "better"}
    vocab_change = None
    if current.get("avg_vocab_richness") is not None and previous.get("avg_vocab_richness") is not None:
        delta = current["avg_vocab_richness"] - previous["avg_vocab_richness"]
        vocab_change = {"delta": round(delta, 4), "direction": "better" if delta > 0 else "worse"}
    return {"filler_words": filler_change, "vocabulary": vocab_change}


@router.get("/speech/sessions")
async def recent_sessions(limit: int = 20, _auth: dict = Depends(require_auth)):
    sessions = get_recent_sessions(limit=limit)
    # Strip full transcript from list view
    for s in sessions:
        s.pop("transcript", None)
        s.pop("metrics_json", None)
    return {"sessions": sessions}


# ── People / Relationship memory ──────────────────────────────────────────────

@router.get("/speech/people")
async def get_people(_auth: dict = Depends(require_auth)):
    this_week = people_this_week()
    all_people = all_known_people(50)
    return {"this_week": this_week, "all_known": all_people}


@router.get("/speech/person/{name}")
async def get_person(name: str, _auth: dict = Depends(require_auth)):
    last = last_conversation(name)
    history = conversation_history(name, limit=10)
    summary = format_last_convo(name)
    return {
        "name": name,
        "summary": summary,
        "last_conversation": last,
        "history": history,
    }


@router.get("/speech/last/{name}")
async def last_talked_to(name: str, _auth: dict = Depends(require_auth)):
    return {"response": format_last_convo(name)}
