"""
Dream Scheduler — nightly background loop.

Fires at 3am. Runs engine → evaluator → selective write-back.
Manual trigger available via POST /dream/run.

Safety guard: if >3 sessions fire in 24h, halts and warns (indicates a bug).
"""
import asyncio
import uuid
from datetime import datetime

from intelligence import unified_memory
from intelligence.dream_engine import generate_session
from intelligence.dream_evaluator import evaluate_session
from observability.logger import log

_MAX_SESSIONS_PER_DAY = 3
_running = False


async def run_dream_scheduler(broadcast_fn=None) -> None:
    """Register as a FastAPI lifespan background task."""
    global _running
    _running = True
    log.info("dream_scheduler_started")

    while _running:
        try:
            now = datetime.now()
            if now.hour == 3 and now.minute < 5:
                await _maybe_run_session(broadcast_fn)
                await asyncio.sleep(3600)           # don't double-fire within the hour
        except Exception as e:
            log.warn("dream_scheduler_error", error=str(e))
        await asyncio.sleep(60)                     # check every minute


async def run_now(broadcast_fn=None) -> dict:
    """Manual trigger — used by POST /dream/run and tests."""
    return await _maybe_run_session(broadcast_fn, force=True)


async def _maybe_run_session(broadcast_fn=None, force: bool = False) -> dict:
    # Safety guard
    sessions_today = await asyncio.to_thread(unified_memory.dream_sessions_today)
    if not force and sessions_today >= _MAX_SESSIONS_PER_DAY:
        log.warn("dream_scheduler_halted",
                 reason=f"already ran {sessions_today} sessions today")
        return {"status": "halted", "sessions_today": sessions_today}

    session_id = uuid.uuid4().hex[:8]
    log.info("dream_session_starting", session_id=session_id)

    await asyncio.to_thread(unified_memory.create_dream_session, session_id)

    if broadcast_fn:
        await broadcast_fn({"type": "dream_session_start", "session_id": session_id})

    try:
        tasks = await generate_session(session_id)
        if not tasks:
            await asyncio.to_thread(
                unified_memory.finish_dream_session, session_id, "failed"
            )
            return {"status": "no_tasks", "session_id": session_id}

        summary = await evaluate_session(session_id, tasks, broadcast_fn)
        return {"status": "done", "session_id": session_id, **summary}

    except Exception as e:
        log.error("dream_session_failed", session_id=session_id, error=str(e))
        await asyncio.to_thread(
            unified_memory.finish_dream_session, session_id, "failed"
        )
        return {"status": "error", "session_id": session_id, "error": str(e)}


def stop_dream_scheduler() -> None:
    global _running
    _running = False
