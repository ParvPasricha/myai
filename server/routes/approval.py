"""
Approval system — sensitive actions (send message, send email) require iOS approval.

POST /approvals/request          — create a pending approval (internal)
GET  /approvals/pending          — iOS polls this
POST /approvals/{id}/approve     — user approves
POST /approvals/{id}/deny        — user denies
POST /approvals/{id}/edit        — user edits content then approves
WS   /ws/approvals               — push to iOS instantly on new request
"""
import asyncio
import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from server.auth import require_auth
from observability.logger import log

router = APIRouter()

_DB_PATH = Path(__file__).parent.parent.parent / "memory" / "approvals.db"
_sqlite: Optional[sqlite3.Connection] = None


def _db() -> sqlite3.Connection:
    global _sqlite
    if _sqlite is None:
        _sqlite = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _sqlite.row_factory = sqlite3.Row
        _sqlite.executescript("""
            CREATE TABLE IF NOT EXISTS approvals (
                id          TEXT PRIMARY KEY,
                created_at  REAL NOT NULL,
                type        TEXT NOT NULL,   -- message | email | action
                recipient   TEXT NOT NULL,
                content     TEXT NOT NULL,
                edited      TEXT DEFAULT '',
                status      TEXT DEFAULT 'pending',  -- pending|approved|denied
                expires_at  REAL
            );
            CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at);
        """)
        _sqlite.commit()
    return _sqlite


# ── WebSocket manager ─────────────────────────────────────────────────────────

class _WS:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)

    def disconnect(self, ws: WebSocket):
        try: self._sockets.remove(ws)
        except ValueError: pass

    async def push(self, data: dict):
        msg  = json.dumps(data)
        dead = []
        for ws in list(self._sockets):
            try: await ws.send_text(msg)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)


_ws = _WS()


# ── Internal helper (called by agents) ────────────────────────────────────────

def create_approval(type_: str, recipient: str, content: str,
                    expires_in: float = 300) -> str:
    appr_id = uuid.uuid4().hex[:10]
    db = _db()
    db.execute(
        "INSERT INTO approvals (id, created_at, type, recipient, content, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (appr_id, time.time(), type_, recipient, content, time.time() + expires_in),
    )
    db.commit()
    log.info("approval_created", id=appr_id, type=type_, to=recipient)
    return appr_id


# ── REST endpoints ────────────────────────────────────────────────────────────

@router.get("/approvals/pending")
async def pending(_auth: dict = Depends(require_auth)):
    rows = _db().execute(
        "SELECT * FROM approvals WHERE status='pending' ORDER BY created_at DESC"
    ).fetchall()
    return {"approvals": [dict(r) for r in rows]}


class EditBody(BaseModel):
    content: str


@router.post("/approvals/{appr_id}/approve")
async def approve(appr_id: str, _auth: dict = Depends(require_auth)):
    row = _db().execute("SELECT * FROM approvals WHERE id=?", (appr_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Not found")
    _db().execute("UPDATE approvals SET status='approved' WHERE id=?", (appr_id,))
    _db().commit()
    await _execute_approval(dict(row))
    return {"ok": True, "id": appr_id}


@router.post("/approvals/{appr_id}/deny")
async def deny(appr_id: str, _auth: dict = Depends(require_auth)):
    _db().execute("UPDATE approvals SET status='denied' WHERE id=?", (appr_id,))
    _db().commit()
    log.info("approval_denied", id=appr_id)
    return {"ok": True, "id": appr_id}


@router.post("/approvals/{appr_id}/edit")
async def edit_and_approve(appr_id: str, body: EditBody, _auth: dict = Depends(require_auth)):
    row = _db().execute("SELECT * FROM approvals WHERE id=?", (appr_id,)).fetchone()
    if not row:
        from fastapi import HTTPException
        raise HTTPException(404, "Not found")
    _db().execute(
        "UPDATE approvals SET status='approved', edited=? WHERE id=?",
        (body.content, appr_id),
    )
    _db().commit()
    updated = dict(row)
    updated["content"] = body.content
    await _execute_approval(updated)
    return {"ok": True, "id": appr_id}


@router.websocket("/ws/approvals")
async def approvals_ws(ws: WebSocket):
    await _ws.connect(ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws.disconnect(ws)


# ── Approval execution ────────────────────────────────────────────────────────

async def _execute_approval(row: dict) -> None:
    content   = row.get("edited") or row.get("content", "")
    recipient = row["recipient"]
    type_     = row["type"]
    log.info("approval_executing", type=type_, to=recipient)

    try:
        if type_ == "message":
            from intelligence.mac_controller import run_applescript_async
            script = f"""
tell application "Messages"
    set targetService to 1st account whose service type = iMessage
    set targetBuddy to participant "{recipient}" of targetService
    send "{content}" to targetBuddy
end tell
"""
            await run_applescript_async(script)

        elif type_ == "email":
            # Use Apple Mail AppleScript to send
            lines  = content.split("\n", 1)
            subject_line = lines[0].replace("Subject: ", "").strip()
            body   = lines[1].strip() if len(lines) > 1 else content
            script = f"""
tell application "Mail"
    set newMsg to make new outgoing message with properties {{subject:"{subject_line}", content:"{body}", visible:false}}
    tell newMsg
        make new to recipient at end of to recipients with properties {{address:"{recipient}"}}
    end tell
    send newMsg
end tell
"""
            from intelligence.mac_controller import run_applescript_async
            await run_applescript_async(script)

    except Exception as e:
        log.warn("approval_execute_failed", error=str(e))


async def push_approval(approval_id: str) -> None:
    """Push a new approval request to all connected iOS clients."""
    row = _db().execute("SELECT * FROM approvals WHERE id=?", (approval_id,)).fetchone()
    if row:
        await _ws.push({"type": "approval_request", **dict(row)})
