"""
WhatsParvDoing dashboard routes.

Public data (no auth — friends access via signed token in URL):
    GET  /dashboard/public          — current dashboard payload
    GET  /ws/dashboard              — WebSocket: real-time Brain State push
    POST /dashboard/location        — iPhone pushes location (JWT required)

Private (JWT required):
    GET  /dashboard/history         — last 24h of Brain State snapshots
    POST /dashboard/activity        — manually set current activity
"""
import asyncio
import json
import time
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, Query
from pydantic import BaseModel

from server.auth import require_auth, verify_token
from intelligence import brain_state as bs
from memory.structured import get_brain_state_history
from research.db import get_today_topic
from observability.logger import log

router = APIRouter()

# ── WebSocket connection manager ──────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self._connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._connections.append(ws)
        log.info("dashboard_ws_connected", total=len(self._connections))

    def disconnect(self, ws: WebSocket):
        self._connections.remove(ws)
        log.info("dashboard_ws_disconnected", total=len(self._connections))

    async def broadcast(self, data: dict):
        """Push JSON to all connected clients."""
        if not self._connections:
            return
        msg = json.dumps(data)
        dead = []
        for ws in list(self._connections):   # iterate snapshot to avoid mutation-during-iteration
            try:
                await ws.send_text(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)   # use disconnect() so log + any future hooks fire

    @property
    def client_count(self) -> int:
        return len(self._connections)


manager = ConnectionManager()


# ── Dashboard payload builder ─────────────────────────────────────────────────

def _build_payload() -> dict:
    """Build the public-facing dashboard payload — no sensitive data."""
    state = bs.get()
    today = datetime.now().date().isoformat()
    topic_row = get_today_topic(today)

    return {
        "current_activity": state.get("current_activity", "idle"),
        "focus_score": state.get("focus", 5),
        "energy_score": state.get("energy", 5),
        "stress_score": state.get("stress", 3),
        "deep_work": state.get("deep_work", False),
        "location": state.get("location", "unknown"),
        "emotion": None,   # populated by vision pipeline
        "today_topic": topic_row["topic"] if topic_row else None,
        "quiz_status": "pending",   # updated by research routes
        "mic_stage": state.get("mic_stage", "push_to_talk"),
        "last_updated": datetime.utcnow().isoformat() + "Z",
    }


async def broadcast_state():
    """Called whenever Brain State changes — pushes update to all WebSocket clients."""
    if manager.client_count == 0:
        return
    payload = _build_payload()
    payload["type"] = "brain_state_update"
    await manager.broadcast(payload)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/dashboard/public")
async def public_dashboard(token: Optional[str] = Query(None)):
    """
    Public endpoint — accessible with a friend token in the URL.
    No token = still returns data (for Parv's own browser).
    Friend tokens are validated but not required for read access.
    """
    if token:
        try:
            verify_token(token)
        except Exception:
            pass   # invalid token → still serve public data (no secrets here)
    return _build_payload()


@router.websocket("/ws/dashboard")
async def dashboard_ws(ws: WebSocket, token: Optional[str] = Query(None)):
    """
    WebSocket endpoint for real-time dashboard updates.
    Sends a snapshot immediately on connect, then pushes on Brain State changes.
    """
    await manager.connect(ws)
    try:
        # Send current state immediately
        payload = _build_payload()
        payload["type"] = "initial_state"
        await ws.send_text(json.dumps(payload))

        # Keep connection alive — server pushes updates via broadcast_state()
        # Client sends pings to keep alive; server echoes pong
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception as e:
        log.warn("dashboard_ws_error", error=str(e))
        try:
            manager.disconnect(ws)
        except Exception:
            pass


class LocationBody(BaseModel):
    location: str           # "home/desk", "gym", "library", "transit", etc.
    lat: Optional[float] = None
    lng: Optional[float] = None

@router.post("/dashboard/location")
async def update_location(body: LocationBody, _auth: dict = Depends(require_auth)):
    """iPhone pushes location updates here."""
    bs.update({"location": body.location})
    log.info("location_updated", location=body.location)
    await broadcast_state()
    return {"ok": True, "location": body.location}


class ActivityBody(BaseModel):
    activity: str

@router.post("/dashboard/activity")
async def update_activity(body: ActivityBody, _auth: dict = Depends(require_auth)):
    """Manually set current activity."""
    bs.update({"current_activity": body.activity})
    await broadcast_state()
    return {"ok": True, "activity": body.activity}


@router.get("/dashboard/history")
async def brain_history(_auth: dict = Depends(require_auth)):
    history = get_brain_state_history(hours=24)
    return {"count": len(history), "history": history}


@router.get("/dashboard/ws/status")
async def ws_status(_auth: dict = Depends(require_auth)):
    return {"connected_clients": manager.client_count}
