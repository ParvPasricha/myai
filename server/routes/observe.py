"""
Observation routes — receive signals from terminal hook, screen monitor,
and trigger autonomous topic research.

POST /observe/terminal    — shell hook sends completed commands here
POST /observe/screen      — screen monitor sends activity snapshots here
POST /learn/topic         — trigger autonomous topic research
GET  /observe/feed        — recent observations (all types)
WS   /ws/observe          — live feed of all observations + research events
"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from server.auth import require_auth
from intelligence import unified_memory
from observability.logger import log

router = APIRouter()


# ── WebSocket manager ─────────────────────────────────────────────────────────

class _Manager:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)

    def disconnect(self, ws: WebSocket):
        try:
            self._sockets.remove(ws)
        except ValueError:
            pass

    async def broadcast(self, data: dict):
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


_ws = _Manager()


async def broadcast_observe(data: dict) -> None:
    await _ws.broadcast(data)


# ── Models ────────────────────────────────────────────────────────────────────

class TerminalObs(BaseModel):
    command: str
    exit_code: int = 0
    cwd: str = ""
    duration_s: float = 0.0


class TopicRequest(BaseModel):
    topic: str
    depth: str = "intermediate"


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/observe/terminal")
async def observe_terminal(body: TerminalObs, _auth: dict = Depends(require_auth)):
    from intelligence.learning_engine import learn_from_terminal

    # Fire-and-forget — don't block the shell
    asyncio.create_task(
        learn_from_terminal(
            command=body.command,
            exit_code=body.exit_code,
            cwd=body.cwd,
            duration_s=body.duration_s,
        )
    )
    # Broadcast to live observers
    asyncio.create_task(broadcast_observe({
        "type":      "terminal",
        "command":   body.command[:120],
        "exit_code": body.exit_code,
        "cwd":       body.cwd,
        "ok":        body.exit_code == 0,
    }))
    return {"ok": True}


@router.post("/learn/topic")
async def learn_topic(body: TopicRequest, _auth: dict = Depends(require_auth)):
    from intelligence.topic_researcher import research_topic

    session_id_holder: dict = {}

    async def _run():
        result = await research_topic(
            topic=body.topic,
            depth=body.depth,
            broadcast_fn=broadcast_observe,
        )
        session_id_holder.update(result)

    asyncio.create_task(_run())
    return {
        "status":  "started",
        "topic":   body.topic,
        "depth":   body.depth,
        "message": "Research running — watch /ws/observe for live updates",
    }


@router.get("/observe/feed")
async def observe_feed(
    n: int = 50,
    obs_type: str = "",
    _auth: dict = Depends(require_auth),
):
    obs = await asyncio.to_thread(
        unified_memory.get_recent_observations,
        obs_type or None, n,
    )
    return {"count": len(obs), "observations": obs}


@router.get("/observe/stats")
async def observe_stats(_auth: dict = Depends(require_auth)):
    db_stats = await asyncio.to_thread(unified_memory.memory_stats)
    terminal = await asyncio.to_thread(unified_memory.get_recent_observations, "terminal", 1000)
    screen   = await asyncio.to_thread(unified_memory.get_recent_observations, "screen",   1000)
    topic    = await asyncio.to_thread(unified_memory.get_recent_observations, "topic",    1000)
    return {
        "terminal_commands": len(terminal),
        "screen_snapshots":  len(screen),
        "topics_researched": len(topic),
        "memory":            db_stats,
        "ws_clients":        _ws.count,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/observe")
async def observe_ws(ws: WebSocket):
    await _ws.connect(ws)
    try:
        # Send last 10 observations on connect
        recent = await asyncio.to_thread(unified_memory.get_recent_observations, None, 10)
        await ws.send_text(json.dumps({"type": "history", "observations": recent}))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws.disconnect(ws)
    except Exception as e:
        log.warn("observe_ws_error", error=str(e))
        _ws.disconnect(ws)
