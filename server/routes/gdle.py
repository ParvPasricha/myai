"""
Guided Dream Learning Engine routes.

POST /gdle/start                  — start a new GDLE session
GET  /gdle/sessions               — list recent sessions
GET  /gdle/session/{id}           — full session detail with concepts
GET  /gdle/session/{id}/guide     — just the learning guide text
WS   /ws/gdle                     — live updates during a session
"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from server.auth import require_auth
from intelligence import unified_memory
from observability.logger import log

router = APIRouter()

_active: dict[str, str] = {}   # session_id → status


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


async def broadcast_gdle(data: dict) -> None:
    await _ws.broadcast(data)


# ── Models ────────────────────────────────────────────────────────────────────

class StartRequest(BaseModel):
    topic: str
    depth: str = "intermediate"
    style: str = ""
    constraints: str = ""


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/gdle/start")
async def start_session(body: StartRequest, _auth: dict = Depends(require_auth)):
    import uuid
    session_id = uuid.uuid4().hex[:8]

    await asyncio.to_thread(
        unified_memory.create_gdle_session,
        session_id, body.topic, body.depth, body.style, body.constraints,
    )
    _active[session_id] = "running"

    async def _run():
        from intelligence.gdle_engine import run_gdle_session
        try:
            await run_gdle_session(
                session_id=session_id,
                topic=body.topic,
                depth=body.depth,
                style=body.style,
                constraints=body.constraints,
                broadcast_fn=broadcast_gdle,
            )
        finally:
            _active.pop(session_id, None)

    asyncio.create_task(_run())

    return {
        "session_id": session_id,
        "topic":      body.topic,
        "depth":      body.depth,
        "status":     "started",
        "message":    "GDLE session running — watch /ws/gdle for live updates",
    }


@router.get("/gdle/sessions")
async def list_sessions(n: int = 10, _auth: dict = Depends(require_auth)):
    sessions = await asyncio.to_thread(unified_memory.get_gdle_sessions, n)
    return {"count": len(sessions), "sessions": sessions}


@router.get("/gdle/session/{session_id}")
async def get_session(session_id: str, _auth: dict = Depends(require_auth)):
    session = await asyncio.to_thread(unified_memory.get_gdle_session, session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.get("/gdle/session/{session_id}/guide")
async def get_guide(session_id: str, _auth: dict = Depends(require_auth)):
    session = await asyncio.to_thread(unified_memory.get_gdle_session, session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "topic": session["topic"], "guide": session.get("guide", "")}


@router.get("/gdle/status")
async def gdle_status(_auth: dict = Depends(require_auth)):
    return {
        "active_sessions": list(_active.keys()),
        "ws_clients":      _ws.count,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/gdle")
async def gdle_ws(ws: WebSocket):
    await _ws.connect(ws)
    try:
        await ws.send_text(json.dumps({
            "type":            "status",
            "active_sessions": list(_active.keys()),
        }))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws.disconnect(ws)
    except Exception as e:
        log.warn("gdle_ws_error", error=str(e))
        _ws.disconnect(ws)
