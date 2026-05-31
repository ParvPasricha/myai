"""
Assistant routes — interactive AI page backend.

GET  /assistant/feed              — personalised content cards (news, study, code, quiz)
POST /assistant/stream            — streaming chat (SSE, token-by-token)
POST /assistant/quiz/generate     — generate N MCQ questions on a topic
POST /assistant/quiz/check        — check a single answer
GET  /assistant/profile           — what the AI knows about the user
POST /assistant/teach             — structured teaching outline for a topic
"""
import asyncio
import json
import time
import uuid
from typing import AsyncIterator, Optional

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from server.auth import require_auth
from server.config import OLLAMA_BASE_URL, OLLAMA_MODEL
from intelligence import unified_memory
from intelligence.learning_engine import get_domain_summary
from intelligence.domain_detector import DOMAIN_KEYWORDS
from observability.logger import log

router = APIRouter()

# ── Ollama streaming ──────────────────────────────────────────────────────────

async def _stream_ollama(
    prompt: str,
    system: str = "",
    session_id: str = "",
) -> AsyncIterator[str]:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    try:
        async with httpx.AsyncClient(timeout=120.0) as c:
            async with c.stream(
                "POST",
                f"{OLLAMA_BASE_URL}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": messages, "stream": True},
            ) as r:
                async for line in r.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                        token = data.get("message", {}).get("content", "")
                        if token:
                            yield f"data: {json.dumps({'token': token})}\n\n"
                        if data.get("done"):
                            yield "data: [DONE]\n\n"
                            return
                    except json.JSONDecodeError:
                        continue
    except Exception as e:
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
        yield "data: [DONE]\n\n"


async def _complete(prompt: str, system: str = "", max_tokens: int = 1024) -> str:
    from server.llm_router import llm
    result = await llm.complete(prompt=prompt, system=system, max_tokens=max_tokens)
    return result.get("text", "")


# ── Feed ──────────────────────────────────────────────────────────────────────

@router.get("/assistant/feed")
async def get_feed(_auth: dict = Depends(require_auth)):
    """
    Generates 6 personalised cards based on domain history + habits.
    Returns fast — uses compact prompts.
    """
    domain_counts = await asyncio.to_thread(get_domain_summary)
    habits        = await asyncio.to_thread(_get_top_habits, 3)
    recent        = await asyncio.to_thread(unified_memory.recent_conversations, 5)

    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    domain_str  = ", ".join(d for d, _ in top_domains) if top_domains else "code, physics, maths"

    recent_topics = "; ".join(
        r["text"][:80] for r in recent
    ) if recent else "general programming and learning"

    system = (
        "You are a sharp personal AI that curates content for a specific user. "
        "Return ONLY valid JSON — no markdown, no explanation."
    )
    prompt = (
        f"User's top domains: {domain_str}.\n"
        f"Recent activity: {recent_topics}.\n"
        f"User habits: {'; '.join(habits) if habits else 'building personal AI'}.\n\n"
        "Generate 6 content cards. JSON format:\n"
        '{"cards": [\n'
        '  {"type": "news|study|code|quiz|explore|challenge",\n'
        '   "domain": "code|physics|maths|business|editing|personal",\n'
        '   "title": "short compelling title",\n'
        '   "description": "2 sentence hook — why this matters to them",\n'
        '   "topic": "the specific topic for deeper interaction",\n'
        '   "difficulty": "beginner|intermediate|advanced"}\n'
        "]}\n"
        "Mix types. Make titles punchy. Base them on the user's actual interests."
    )

    try:
        raw = await _complete(prompt, system, max_tokens=800)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        cards = json.loads(raw[start:end]).get("cards", []) if start >= 0 else []
    except Exception as e:
        log.warn("feed_generation_failed", error=str(e))
        cards = _fallback_cards(domain_str)

    return {"cards": cards[:6], "generated_at": time.time(),
            "domains": dict(top_domains)}


def _get_top_habits(n: int) -> list[str]:
    try:
        col = unified_memory._col("intel_habits")
        if col.count() == 0:
            return []
        results = col.get(limit=n, include=["documents"])
        return (results.get("documents") or [])[:n]
    except Exception:
        return []


def _fallback_cards(domains: str) -> list[dict]:
    return [
        {"type": "study",   "domain": "code",    "title": "How async/await actually works",
         "description": "Understanding the event loop at a deeper level changes how you write code.",
         "topic": "Python async event loop internals", "difficulty": "intermediate"},
        {"type": "news",    "domain": "code",    "title": "What's shipping in Python 3.14",
         "description": "New features landing soon — some will change how you write daily code.",
         "topic": "Python 3.14 new features", "difficulty": "beginner"},
        {"type": "quiz",    "domain": "physics", "title": "Test your quantum mechanics",
         "description": "5 questions on wave-particle duality and superposition.",
         "topic": "quantum mechanics fundamentals", "difficulty": "intermediate"},
        {"type": "code",    "domain": "code",    "title": "Build a rate limiter from scratch",
         "description": "Token bucket vs sliding window — implement both and benchmark them.",
         "topic": "rate limiting algorithms", "difficulty": "advanced"},
        {"type": "explore", "domain": "maths",   "title": "Why Fourier transforms are everywhere",
         "description": "From audio to image compression — the same idea runs it all.",
         "topic": "Fourier transform intuition", "difficulty": "intermediate"},
        {"type": "challenge","domain": "business","title": "Price your SaaS product",
         "description": "Walk through value-based pricing for a developer tool from scratch.",
         "topic": "SaaS pricing strategy", "difficulty": "beginner"},
    ]


# ── Streaming chat ────────────────────────────────────────────────────────────

class StreamBody(BaseModel):
    prompt: str
    mode: str = "chat"       # chat | teach | work | explain
    topic: Optional[str] = None
    session_id: Optional[str] = None
    context: Optional[str] = None


_TONE = (
    "Direct, concise, no filler. Don't flatter or validate to be agreeable. "
    "If something is wrong, say so. No motivational language. "
    "Don't repeat back what was just said. No sign-offs."
)

_MEMORY_RULES = (
    "\nMEMORY: Only use what's in this session. "
    "Can't cite it from this conversation? Don't assert it. "
    "Missing info → say so plainly."
)

_MODE_SYSTEMS = {
    "chat": (
        "You are PARV-AI, Parv's personal AI. "
        + _TONE
    ),
    "teach": (
        "You are teaching Parv a topic. "
        "Be precise. Build from fundamentals to depth. "
        "Use concrete examples and code where it helps. "
        "Don't oversimplify and don't pad. "
        "If something has nuance, show the nuance — don't flatten it. "
        + _TONE
    ),
    "work": (
        "You are pair-programming with Parv. "
        "Write working code. Call out edge cases and tradeoffs directly. "
        "If the approach has a problem, say so before writing it. "
        "No commentary filler between code blocks. "
        + _TONE
    ),
    "explain": (
        "Explain this to Parv. "
        "Lead with the core idea in one sentence. "
        "Then go as deep as needed. "
        "Don't soften technical reality. "
        + _TONE
    ),
}


@router.post("/assistant/stream")
async def stream_chat(body: StreamBody, _auth: dict = Depends(require_auth)):
    session_id = body.session_id or uuid.uuid4().hex[:8]

    from memory import working as wm
    session_ctx = await asyncio.to_thread(
        wm.get_context_block, session_id, 600
    )

    system = _MODE_SYSTEMS.get(body.mode, _MODE_SYSTEMS["chat"])
    system += _MEMORY_RULES
    if session_ctx:
        system += f"\n\n[CONVERSATION SO FAR — source: current session]\n{session_ctx}"
    if body.context:
        system += f"\n\n[TOPIC CONTEXT — source: user selected]\n{body.context}"

    prompt = body.prompt
    if body.topic and body.mode == "teach":
        prompt = f"Teach me about: {body.topic}\n\nSpecific question: {body.prompt}"

    log.info("assistant_stream", mode=body.mode, session=session_id,
             prompt_len=len(prompt))

    return StreamingResponse(
        _stream_ollama(prompt, system, session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ── Teaching outline ──────────────────────────────────────────────────────────

class TeachBody(BaseModel):
    topic: str
    level: str = "intermediate"   # beginner | intermediate | advanced


@router.post("/assistant/teach")
async def generate_outline(body: TeachBody, _auth: dict = Depends(require_auth)):
    """Returns a structured teaching plan for a topic before streaming starts."""
    system = "Return ONLY valid JSON. No markdown."
    prompt = (
        f"Create a teaching plan for: '{body.topic}' at {body.level} level.\n"
        '{"title": "...", "estimated_minutes": 15, '
        '"sections": [{"title": "...", "key_points": ["...", "..."], "has_code": true/false}], '
        '"prerequisites": ["..."], "what_you_will_build": "..."}'
    )
    try:
        raw = await _complete(prompt, system, max_tokens=600)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        plan  = json.loads(raw[start:end]) if start >= 0 else {}
    except Exception:
        plan  = {"title": body.topic, "sections": [], "prerequisites": [],
                 "estimated_minutes": 15, "what_you_will_build": ""}

    return {"topic": body.topic, "level": body.level, "plan": plan}


# ── Quiz ──────────────────────────────────────────────────────────────────────

class QuizBody(BaseModel):
    topic: str
    n: int = 5
    level: str = "intermediate"


# Server-side answer store (in-memory, keyed by quiz_id)
_quiz_store: dict[str, list[dict]] = {}


@router.post("/assistant/quiz/generate")
async def generate_quiz(body: QuizBody, _auth: dict = Depends(require_auth)):
    system = (
        "You are a precise quiz generator. "
        "Return ONLY valid JSON with no markdown fences."
    )
    prompt = (
        f"Generate {body.n} multiple-choice questions about '{body.topic}' "
        f"at {body.level} level.\n"
        '{"questions": [{"id": 1, "question": "...", '
        '"options": ["A. ...", "B. ...", "C. ...", "D. ..."], '
        '"correct": "A", "explanation": "..."}]}'
    )

    try:
        raw = await _complete(prompt, system, max_tokens=1200)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        data  = json.loads(raw[start:end]) if start >= 0 else {}
        questions = data.get("questions", [])
    except Exception as e:
        log.warn("quiz_gen_failed", error=str(e))
        questions = []

    quiz_id = uuid.uuid4().hex[:8]
    _quiz_store[quiz_id] = questions

    # Strip correct answer before sending to client
    client_questions = [
        {k: v for k, v in q.items() if k != "correct" and k != "explanation"}
        for q in questions
    ]

    return {
        "quiz_id": quiz_id,
        "topic": body.topic,
        "total": len(client_questions),
        "questions": client_questions,
    }


class CheckBody(BaseModel):
    quiz_id: str
    question_id: int
    answer: str   # "A", "B", "C", or "D"


@router.post("/assistant/quiz/check")
async def check_answer(body: CheckBody, _auth: dict = Depends(require_auth)):
    questions = _quiz_store.get(body.quiz_id, [])
    q = next((q for q in questions if q["id"] == body.question_id), None)
    if not q:
        return {"correct": False, "explanation": "Question not found."}
    correct = body.answer.upper() == q.get("correct", "").upper()
    return {
        "correct": correct,
        "correct_answer": q.get("correct"),
        "explanation": q.get("explanation", ""),
    }


# ── Profile ───────────────────────────────────────────────────────────────────

@router.get("/assistant/profile")
async def get_profile(_auth: dict = Depends(require_auth)):
    """What the AI knows about the user — built from unified memory."""
    stats        = await asyncio.to_thread(unified_memory.memory_stats)
    domain_counts = await asyncio.to_thread(get_domain_summary)
    habits       = await asyncio.to_thread(_get_top_habits, 6)
    decisions    = await asyncio.to_thread(
        unified_memory.search_decisions, None, None, None, 5
    )
    recent       = await asyncio.to_thread(unified_memory.recent_conversations, 3)

    total_convs = stats.get("intel_conversations", 0)
    top_domains = sorted(domain_counts.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_conversations": total_convs,
        "total_decisions": stats.get("decisions", 0),
        "top_domains": [{"domain": d, "count": c} for d, c in top_domains],
        "detected_habits": habits,
        "recent_decisions": decisions,
        "recent_topics": [r["text"][:120] for r in recent],
        "memory_breakdown": stats,
    }
