"""
Parallel Executor — Phase 10.

Decomposes a project description into tasks and runs independent ones
simultaneously as subprocesses. Task dependencies determine order.

Flow:
  1. POST /intelligence/plan          → LLM decomposes into Task list
  2. POST /intelligence/plan/{id}/run → execute_plan() fires
  3. GET  /intelligence/plan/{id}     → poll status while running
  4. WS   /ws/intelligence            → live updates pushed as tasks complete

Plan state stored in Redis with 24-hour TTL.
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional

import redis

from server.config import REDIS_URL
from observability.logger import log

_PLAN_TTL = 86_400  # 24 h


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE    = "done"
    FAILED  = "failed"
    SKIPPED = "skipped"


@dataclass
class Task:
    id:          str
    name:        str
    description: str
    command:     str
    depends_on:  list[str] = field(default_factory=list)
    status:      str       = TaskStatus.PENDING
    output:      str       = ""
    error:       str       = ""
    started_at:  Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class Plan:
    id:          str
    description: str
    domain:      str
    tasks:       list[Task]  = field(default_factory=list)
    created_at:  float       = field(default_factory=time.time)
    status:      str         = "ready"   # ready / running / done / failed


# ── Redis helpers ─────────────────────────────────────────────────────────────

def _redis() -> Optional[redis.Redis]:
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True,
                           socket_connect_timeout=1)
        r.ping()
        return r
    except Exception:
        return None


def _save_plan(plan: Plan) -> None:
    r = _redis()
    if r:
        data = asdict(plan)
        r.setex(f"intel:plan:{plan.id}", _PLAN_TTL, json.dumps(data))


def _load_plan(plan_id: str) -> Optional[Plan]:
    r = _redis()
    if not r:
        return None
    raw = r.get(f"intel:plan:{plan_id}")
    if not raw:
        return None
    data = json.loads(raw)
    tasks = [Task(**t) for t in data.pop("tasks")]
    return Plan(tasks=tasks, **data)


# ── Plan creation ─────────────────────────────────────────────────────────────

async def create_plan(description: str, context: str = "",
                      max_parallel: int = 4) -> Plan:
    """
    Use the local LLM to decompose a project description into parallel tasks.
    Falls back to a single manual task if LLM fails.
    """
    from server.llm_router import llm

    system = (
        "You are a senior software project planner. "
        "Decompose the given project into concrete parallel tasks. "
        "Respond ONLY with valid JSON (no markdown): "
        '{"tasks": [{"id": "t1", "name": "...", "description": "...", '
        '"command": "...", "depends_on": []}]}. '
        f"Use at most {max_parallel} tasks. "
        "Commands should be shell commands or start with 'manual:' for steps "
        "that require human action."
    )
    prompt = (
        f"Project: {description}\n"
        f"Context: {context or 'none'}\n\n"
        "Decompose into parallel tasks as JSON."
    )

    plan_id = uuid.uuid4().hex[:8]
    tasks: list[Task] = []

    try:
        result = await llm.complete(prompt=prompt, system=system)
        text = result.get("text", "")
        start = text.find("{")
        end = text.rfind("}") + 1
        if start >= 0 and end > start:
            parsed = json.loads(text[start:end])
            for i, t in enumerate(parsed.get("tasks", [])):
                tasks.append(Task(
                    id=t.get("id", f"t{i+1}"),
                    name=t.get("name", f"Task {i+1}"),
                    description=t.get("description", ""),
                    command=t.get("command", "echo done"),
                    depends_on=t.get("depends_on", []),
                ))
    except Exception as e:
        log.warn("plan_llm_error", error=str(e))

    if not tasks:
        tasks = [Task(id="t1", name="Execute project",
                      description=description, command="manual: run manually")]

    plan = Plan(
        id=plan_id, description=description,
        domain=context[:50] if context else "general", tasks=tasks,
    )
    _save_plan(plan)
    log.info("plan_created", plan_id=plan_id, task_count=len(tasks))
    return plan


# ── Plan execution ────────────────────────────────────────────────────────────

async def execute_plan(
    plan_id: str,
    broadcast_fn=None,          # async callable(dict) for WebSocket push
) -> Plan:
    """
    Execute a plan, running independent tasks in parallel.
    Tasks with failed dependencies are automatically skipped.
    """
    plan = _load_plan(plan_id)
    if not plan:
        raise ValueError(f"Plan {plan_id} not found")

    plan.status = "running"
    _save_plan(plan)

    completed: set[str] = set()
    failed:    set[str] = set()
    running:   dict[str, asyncio.Task] = {}   # task_id → asyncio.Task

    async def _run(task: Task) -> None:
        task.status = TaskStatus.RUNNING
        task.started_at = time.time()
        _save_plan(plan)
        if broadcast_fn:
            await broadcast_fn({"type": "plan_update", **asdict(plan)})

        try:
            if task.command.startswith("manual:"):
                task.output = f"[Manual] {task.command[7:].strip()}"
                task.status = TaskStatus.DONE
            else:
                proc = await asyncio.create_subprocess_shell(
                    task.command,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    limit=65_536,
                )
                try:
                    stdout, _ = await asyncio.wait_for(
                        proc.communicate(), timeout=120
                    )
                    task.output = (stdout or b"").decode(
                        "utf-8", errors="replace"
                    )[:2000]
                    task.status = (
                        TaskStatus.DONE
                        if proc.returncode == 0
                        else TaskStatus.FAILED
                    )
                    if proc.returncode != 0:
                        task.error = f"exit {proc.returncode}"
                except asyncio.TimeoutError:
                    proc.kill()
                    task.status = TaskStatus.FAILED
                    task.error = "timeout (120 s)"
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)

        task.finished_at = time.time()
        _save_plan(plan)
        if broadcast_fn:
            await broadcast_fn({"type": "plan_update", **asdict(plan)})

        (completed if task.status == TaskStatus.DONE else failed).add(task.id)

    while True:
        # Skip tasks whose dependencies failed
        for t in plan.tasks:
            if t.status == TaskStatus.PENDING and any(
                dep in failed for dep in t.depends_on
            ):
                t.status = TaskStatus.SKIPPED
                _save_plan(plan)

        # Launch tasks that are ready
        ready = [
            t for t in plan.tasks
            if t.status == TaskStatus.PENDING
            and all(dep in completed for dep in t.depends_on)
            and t.id not in running
        ]
        for t in ready:
            running[t.id] = asyncio.create_task(_run(t))

        if not running:
            break

        done_set, _ = await asyncio.wait(
            running.values(), return_when=asyncio.FIRST_COMPLETED
        )
        for tid in list(running):
            if running[tid] in done_set:
                del running[tid]

    statuses = {t.status for t in plan.tasks}
    plan.status = (
        "failed" if TaskStatus.FAILED in statuses
        else "done"
    )
    _save_plan(plan)
    log.info("plan_executed", plan_id=plan_id, status=plan.status,
             done=len(completed), failed=len(failed))
    return plan


def get_plan(plan_id: str) -> Optional[Plan]:
    return _load_plan(plan_id)


def list_plans(n: int = 20) -> list[dict]:
    """List recent plan IDs from Redis (best-effort scan)."""
    r = _redis()
    if not r:
        return []
    try:
        keys = list(r.scan_iter("intel:plan:*", count=100))[:n]
        plans = []
        for k in keys:
            raw = r.get(k)
            if raw:
                data = json.loads(raw)
                plans.append({
                    "id": data["id"],
                    "description": data["description"],
                    "status": data["status"],
                    "created_at": data["created_at"],
                    "task_count": len(data.get("tasks", [])),
                })
        plans.sort(key=lambda p: p["created_at"], reverse=True)
        return plans
    except Exception:
        return []
