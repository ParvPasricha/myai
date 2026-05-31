"""
Agents routes — Jarvis task management.

POST /agents/task           — submit task to Jarvis / head agent
GET  /agents/tasks          — recent tasks + statuses
GET  /agents/task/{id}      — full task + results
GET  /agents/status         — agent roster + queue depth
DELETE /agents/task/{id}    — cancel pending task
WS   /ws/agents             — live updates as tasks run
"""
import asyncio
import json

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

from server.auth import require_auth
from agents import task_queue
from agents.registry import list_capabilities
from observability.logger import log

router = APIRouter()


class _WS:
    def __init__(self):
        self._sockets: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self._sockets.append(ws)

    def disconnect(self, ws: WebSocket):
        try: self._sockets.remove(ws)
        except ValueError: pass

    async def broadcast(self, data: dict):
        msg  = json.dumps(data)
        dead = []
        for ws in list(self._sockets):
            try: await ws.send_text(msg)
            except Exception: dead.append(ws)
        for ws in dead: self.disconnect(ws)


_ws = _WS()


async def broadcast_agents(data: dict) -> None:
    await _ws.broadcast(data)


class TaskBody(BaseModel):
    input: str
    speak: bool = True


@router.post("/agents/task")
async def submit_task(body: TaskBody, _auth: dict = Depends(require_auth)):
    from agents.head_agent import handle as jarvis_handle

    async def _run():
        await jarvis_handle(body.input, broadcast_fn=broadcast_agents, speak=body.speak)

    asyncio.create_task(_run())
    return {"status": "started", "message": "Jarvis is on it — watch /ws/agents for updates."}


@router.get("/agents/tasks")
async def list_tasks(limit: int = 20, _auth: dict = Depends(require_auth)):
    tasks = await asyncio.to_thread(task_queue.recent_tasks, limit)
    return {"count": len(tasks), "tasks": tasks}


@router.get("/agents/task/{task_id}")
async def get_task(task_id: str, _auth: dict = Depends(require_auth)):
    task    = await asyncio.to_thread(task_queue.get_task, task_id)
    results = await asyncio.to_thread(task_queue.get_results, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(404, "Task not found")
    return {"task": task, "results": results}


@router.delete("/agents/task/{task_id}")
async def cancel_task(task_id: str, _auth: dict = Depends(require_auth)):
    task = await asyncio.to_thread(task_queue.get_task, task_id)
    if not task:
        from fastapi import HTTPException
        raise HTTPException(404, "Task not found")
    if task["status"] == "pending":
        await asyncio.to_thread(task_queue.fail, task_id, "Cancelled by user")
        return {"ok": True}
    return {"ok": False, "reason": f"Task is {task['status']} — cannot cancel"}


@router.get("/agents/status")
async def agent_status(_auth: dict = Depends(require_auth)):
    pending = await asyncio.to_thread(task_queue.pending_count)
    return {
        "capabilities": list_capabilities(),
        "pending_tasks": pending,
        "ws_clients": len(_ws._sockets),
    }


@router.websocket("/ws/agents")
async def agents_ws(ws: WebSocket):
    await _ws.connect(ws)
    try:
        pending = await asyncio.to_thread(task_queue.pending_count)
        await ws.send_text(json.dumps({
            "type": "status",
            "pending": pending,
            "capabilities": list_capabilities(),
        }))
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        _ws.disconnect(ws)
    except Exception as e:
        log.warn("agents_ws_error", error=str(e))
        _ws.disconnect(ws)
