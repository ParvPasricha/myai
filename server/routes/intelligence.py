"""
Intelligence Layer routes — Phase 10.

Memory:
  GET  /intelligence/memory/search?q=&n=    — semantic search across all intel collections
  GET  /intelligence/memory/stats           — counts per collection
  GET  /intelligence/memory/recent          — last N conversations
  GET  /intelligence/decisions?domain=&actor= — decision history
  POST /intelligence/decisions              — log a decision

Parallel planner:
  POST /intelligence/plan                   — LLM decomposes → Task list
  GET  /intelligence/plan/{id}              — poll status
  POST /intelligence/plan/{id}/run          — fire execution
  GET  /intelligence/plans                  — list recent plans

Overwatcher:
  GET  /intelligence/overwatcher/graph      — full code + service graph
  GET  /intelligence/overwatcher/status     — summary stats

Live:
  WS   /ws/intelligence                     — graph + plan updates pushed here
"""
import asyncio
import json
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from server.auth import require_auth
from intelligence import unified_memory, parallel_executor
from intelligence.overwatcher import get_graph
from intelligence.learning_engine import get_domain_summary
from observability.logger import log

router = APIRouter()


# ── WebSocket manager ─────────────────────────────────────────────────────────

class _Manager:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)
        log.info("intel_ws_connected", total=len(self._sockets))

    def disconnect(self, ws: WebSocket):
        try:
            self._sockets.remove(ws)
        except ValueError:
            pass
        log.info("intel_ws_disconnected", total=len(self._sockets))

    async def broadcast(self, data: dict):
        if not self._sockets:
            return
        msg = json.dumps(data)
        dead = []
        for ws in list(self._sockets):
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)

    @property
    def count(self) -> int:
        return len(self._sockets)


_ws_manager = _Manager()


async def broadcast_intelligence(data: dict) -> None:
    """Called by overwatcher and parallel_executor to push live updates."""
    await _ws_manager.broadcast(data)


# ── Memory endpoints ──────────────────────────────────────────────────────────

@router.get("/intelligence/memory/search")
async def memory_search(
    q: str = Query(..., min_length=1),
    n: int = Query(3, ge=1, le=10),
    _auth: dict = Depends(require_auth),
):
    results = await asyncio.to_thread(unified_memory.search_memory, q, n)
    total = sum(len(v) for v in results.values())
    return {"query": q, "total": total, "results": results}


@router.get("/intelligence/memory/stats")
async def memory_stats(_auth: dict = Depends(require_auth)):
    stats = await asyncio.to_thread(unified_memory.memory_stats)
    domain_counts = await asyncio.to_thread(get_domain_summary)
    return {"stats": stats, "domain_counts": domain_counts}


@router.get("/intelligence/memory/recent")
async def memory_recent(
    n: int = Query(10, ge=1, le=50),
    _auth: dict = Depends(require_auth),
):
    convs = await asyncio.to_thread(unified_memory.recent_conversations, n)
    return {"count": len(convs), "conversations": convs}


@router.get("/intelligence/decisions")
async def get_decisions(
    domain: Optional[str] = None,
    actor: Optional[str] = None,
    n: int = Query(20, ge=1, le=100),
    _auth: dict = Depends(require_auth),
):
    decisions = await asyncio.to_thread(
        unified_memory.search_decisions, domain, actor, None, n
    )
    return {"count": len(decisions), "decisions": decisions}


class DecisionBody(BaseModel):
    actor: str = "user"
    content: str
    reasoning: str = ""
    domain: str = "general"
    decision_type: str = "action"
    tags: list[str] = []


@router.post("/intelligence/decisions")
async def log_decision(
    body: DecisionBody,
    _auth: dict = Depends(require_auth),
):
    decision_id = await asyncio.to_thread(
        unified_memory.log_decision,
        body.actor, body.content, body.reasoning,
        body.domain, body.decision_type, body.tags,
    )
    return {"ok": True, "decision_id": decision_id}


# ── Parallel planner endpoints ────────────────────────────────────────────────

class PlanBody(BaseModel):
    description: str
    context: str = ""
    max_parallel: int = 4


@router.post("/intelligence/plan")
async def create_plan(body: PlanBody, _auth: dict = Depends(require_auth)):
    plan = await parallel_executor.create_plan(
        description=body.description,
        context=body.context,
        max_parallel=body.max_parallel,
    )
    return {
        "plan_id": plan.id,
        "task_count": len(plan.tasks),
        "tasks": [asdict(t) for t in plan.tasks],
    }


@router.get("/intelligence/plans")
async def list_plans(
    n: int = Query(10, ge=1, le=50),
    _auth: dict = Depends(require_auth),
):
    plans = await asyncio.to_thread(parallel_executor.list_plans, n)
    return {"count": len(plans), "plans": plans}


@router.get("/intelligence/plan/{plan_id}")
async def get_plan(plan_id: str, _auth: dict = Depends(require_auth)):
    plan = parallel_executor.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    return asdict(plan)


@router.post("/intelligence/plan/{plan_id}/run")
async def run_plan(plan_id: str, _auth: dict = Depends(require_auth)):
    plan = parallel_executor.get_plan(plan_id)
    if not plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    asyncio.create_task(
        parallel_executor.execute_plan(
            plan_id, broadcast_fn=broadcast_intelligence
        )
    )
    return {"ok": True, "plan_id": plan_id, "status": "started"}


# ── Overwatcher endpoints ─────────────────────────────────────────────────────

@router.get("/intelligence/overwatcher/graph")
async def code_graph(_auth: dict = Depends(require_auth)):
    graph = await asyncio.to_thread(get_graph)
    return graph


@router.get("/intelligence/overwatcher/status")
async def overwatcher_status(_auth: dict = Depends(require_auth)):
    graph = await asyncio.to_thread(get_graph)
    nodes = graph.get("nodes", [])
    services = [n for n in nodes if n.get("type") == "service"]
    files    = [n for n in nodes if n.get("type") == "file"]
    return {
        "file_count":    len(files),
        "service_count": len(services),
        "alive_services": sum(1 for s in services if s.get("alive")),
        "edge_count":    len(graph.get("edges", [])),
        "last_updated":  graph.get("last_updated", 0),
        "ws_clients":    _ws_manager.count,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/intelligence")
async def intelligence_ws(ws: WebSocket):
    await _ws_manager.connect(ws)
    try:
        # Push current graph immediately on connect
        graph = await asyncio.to_thread(get_graph)
        await ws.send_text(json.dumps({"type": "graph_update", **graph}))

        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws_manager.disconnect(ws)
    except Exception as e:
        log.warn("intel_ws_error", error=str(e))
        _ws_manager.disconnect(ws)
