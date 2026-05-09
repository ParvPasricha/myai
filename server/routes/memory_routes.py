"""
Memory API routes:
    GET  /memory/search?q=...       — semantic search across all collections
    GET  /memory/recall?q=...       — natural language item/fact lookup
    GET  /memory/stats              — counts per collection + DB sizes
    POST /memory/distill            — trigger manual distillation
    POST /memory/fact               — manually add a fact
    POST /memory/goal               — add a goal
    GET  /memory/goals              — list active goals
    GET  /memory/item?q=...         — find where an item was last seen
    GET  /memory/brain_history      — Brain State history last 24h
"""
import time
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from server.auth import require_auth
from memory import semantic, structured, episodic, working
from observability.logger import log

router = APIRouter()


@router.get("/memory/search")
async def memory_search(q: str = Query(..., min_length=2),
                        _auth: dict = Depends(require_auth)):
    results = semantic.search_all(q, n_each=3)
    return {"query": q, "results": results}


@router.get("/memory/recall")
async def memory_recall(q: str = Query(..., min_length=2),
                        _auth: dict = Depends(require_auth)):
    """Natural language recall — checks items, facts, episodic FTS, and goals."""
    output = {}

    # Item location
    items = structured.find_item_fuzzy(q)
    if items:
        import time as _t
        best = items[0]
        age_h = round((_t.time() - best["last_seen"]) / 3600, 1)
        output["item"] = {
            "object": best["object_class"],
            "zone": best["zone_name"],
            "last_seen_hours_ago": age_h,
        }

    # Episodic FTS
    convo_hits = episodic.search(q, limit=3)
    if convo_hits:
        output["conversations"] = [
            {"role": h["role"], "content": h["content"][:200], "ts": h["timestamp"]}
            for h in convo_hits
        ]

    # Semantic
    semantic_hits = semantic.search_all(q, n_each=2)
    if semantic_hits:
        output["memories"] = [{"text": h["text"][:200]} for h in semantic_hits[:3]]

    return {"query": q, **output}


@router.get("/memory/stats")
async def memory_stats(_auth: dict = Depends(require_auth)):
    sem = semantic.stats()
    return {
        "semantic": sem,
        "episodic_recent_24h": len(episodic.get_recent(hours=24)),
        "active_goals": len(structured.get_active_goals()),
    }


@router.post("/memory/distill")
async def manual_distill(_auth: dict = Depends(require_auth)):
    from memory.distill import run_distillation
    log.info("manual_distillation_triggered")
    await run_distillation()
    return {"ok": True}


class FactBody(BaseModel):
    text: str
    category: str = "preference"

@router.post("/memory/fact")
async def add_fact(body: FactBody, _auth: dict = Depends(require_auth)):
    doc_id = semantic.add_fact(body.text, body.category)
    return {"ok": True, "id": doc_id}


class GoalBody(BaseModel):
    description: str
    domain: str | None = None
    target_date: str | None = None

@router.post("/memory/goal")
async def add_goal(body: GoalBody, _auth: dict = Depends(require_auth)):
    goal_id = structured.add_goal(body.description, body.domain, body.target_date)
    return {"ok": True, "id": goal_id}

@router.get("/memory/goals")
async def get_goals(_auth: dict = Depends(require_auth)):
    return {"goals": structured.get_active_goals()}


@router.get("/memory/item")
async def find_item(q: str = Query(..., min_length=1),
                    _auth: dict = Depends(require_auth)):
    items = structured.find_item_fuzzy(q)
    if not items:
        return {"found": False, "query": q}
    import time as _t
    best = items[0]
    age_h = round((_t.time() - best["last_seen"]) / 3600, 1)
    return {
        "found": True,
        "object": best["object_class"],
        "zone": best["zone_name"],
        "last_seen_hours_ago": age_h,
        "confidence": best["confidence"],
    }


@router.get("/memory/brain_history")
async def brain_history(hours: int = 24, _auth: dict = Depends(require_auth)):
    history = structured.get_brain_state_history(hours=hours)
    return {"count": len(history), "history": history}
