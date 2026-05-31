"""
Dream System routes.

GET  /dream/sessions            — recent dream sessions (summary)
GET  /dream/session/{id}        — full session detail with all tasks + scores
POST /dream/run                 — manually trigger a dream session
GET  /dream/approved            — approved dream patterns in memory
DELETE /dream/approved/{id}     — remove an approved dream pattern
GET  /dream/status              — current mode (wake / dreaming / idle)
WS   /ws/dream                  — live updates during a dream session
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
_active_session: str | None = None


async def broadcast_dream(data: dict) -> None:
    await _ws.broadcast(data)


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/dream/sessions")
async def list_sessions(
    n: int = 10,
    _auth: dict = Depends(require_auth),
):
    sessions = await asyncio.to_thread(unified_memory.get_dream_sessions, n)
    return {"count": len(sessions), "sessions": sessions}


@router.get("/dream/session/{session_id}")
async def get_session(session_id: str, _auth: dict = Depends(require_auth)):
    session = await asyncio.to_thread(unified_memory.get_dream_session, session_id)
    if not session:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/dream/run")
async def trigger_dream(_auth: dict = Depends(require_auth)):
    global _active_session
    if _active_session:
        return {"status": "already_running", "session_id": _active_session}

    async def _run():
        global _active_session
        from intelligence.dream_scheduler import run_now
        result = await run_now(broadcast_fn=broadcast_dream)
        _active_session = None
        return result

    task = asyncio.create_task(_run())
    # Peek at the session_id without awaiting
    _active_session = "pending"
    return {"status": "started", "message": "Dream session running — watch /ws/dream for live updates"}


@router.get("/dream/approved")
async def list_approved(
    n: int = 20,
    _auth: dict = Depends(require_auth),
):
    dreams = await asyncio.to_thread(unified_memory.get_approved_dreams, n)
    return {"count": len(dreams), "dreams": dreams}


@router.delete("/dream/approved/{dream_id}")
async def remove_dream(dream_id: str, _auth: dict = Depends(require_auth)):
    deleted = await asyncio.to_thread(unified_memory.delete_dream, dream_id)
    return {"ok": deleted, "dream_id": dream_id}


@router.get("/dream/status")
async def dream_status(_auth: dict = Depends(require_auth)):
    sessions_today = await asyncio.to_thread(unified_memory.dream_sessions_today)
    mode = "dreaming" if _active_session else "wake"
    return {
        "mode":           mode,
        "active_session": _active_session,
        "sessions_today": sessions_today,
        "ws_clients":     _ws.count,
    }


# ── WebSocket ─────────────────────────────────────────────────────────────────

@router.websocket("/ws/dream")
async def dream_ws(ws: WebSocket):
    await _ws.connect(ws)
    try:
        # Send current status immediately
        sessions_today = await asyncio.to_thread(unified_memory.dream_sessions_today)
        await ws.send_text(json.dumps({
            "type":           "status",
            "mode":           "dreaming" if _active_session else "wake",
            "sessions_today": sessions_today,
        }))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws.disconnect(ws)
    except Exception as e:
        log.warn("dream_ws_error", error=str(e))
        _ws.disconnect(ws)
