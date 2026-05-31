"""
Head Agent — Jarvis as orchestrator.

Flow:
  1. Receive natural language task from user (voice or text)
  2. LLM decomposes into typed subtasks with required capabilities
  3. Dispatch each subtask to matching agent via registry
  4. Poll until all done (or timeout)
  5. LLM synthesises all results into a Jarvis-style spoken response
  6. Speak + broadcast result
"""
import asyncio
import json
import time
import uuid
from typing import Optional

from agents import task_queue
from observability.logger import log

_DECOMPOSE_SYSTEM = """\
You are the task decomposition engine for J.A.R.V.I.S.
Break the user's request into concrete subtasks, each handled by one specialist agent.

Available agent capabilities:
  research           — web search and deep synthesis on any topic
  email              — read inbox, draft, send via Apple Mail (needs approval to send)
  sales_outreach     — draft personalised outreach messages for leads
  business_update    — generate status digests and weekly summaries
  project_planning   — create structured plans with phases and milestones
  project_oversight  — check project status, flag blockers
  backend_review     — review Python/FastAPI code for correctness
  frontend_review    — review React/Next.js code
  security_review    — OWASP audit: auth, injection, secrets
  db_review          — schema review, migration safety, query optimisation
  integration_check  — verify services connect end-to-end
  music              — control Apple Music, pick music by mood
  reminder           — create or list Apple Reminders
  browser            — browse the web, fill forms, scrape pages
  message            — send iMessage (needs approval)

Return ONLY valid JSON:
[{"capability": "research", "payload": {"query": "..."}}, ...]

If the task needs only one agent, return a single-element array.
If the task can be done entirely by Jarvis without subagents, return: []
"""

_SYNTHESISE_SYSTEM = """\
You are J.A.R.V.I.S. Synthesise the subagent results below into a single spoken response.
Be concise — three sentences max unless a detailed briefing was requested.
British tone. Address Parv as "sir" where natural. No markdown.
"""

TASK_TIMEOUT = 120   # seconds


async def handle(
    user_input: str,
    broadcast_fn=None,
    speak: bool = True,
) -> str:
    """Main entry point — Jarvis handles a user request end-to-end."""
    from server.llm_router import llm
    from agents.registry import dispatch

    session_id = uuid.uuid4().hex[:8]
    log.info("jarvis_handle", session=session_id, input=user_input[:80])

    if broadcast_fn:
        await broadcast_fn({"type": "jarvis_thinking", "session_id": session_id})

    # Step 1: Decompose
    try:
        decomp = await llm.complete(
            prompt=f"User request: {user_input}",
            system=_DECOMPOSE_SYSTEM,
            max_tokens=400,
        )
        raw = decomp.get("text", "[]")
        start, end = raw.find("["), raw.rfind("]") + 1
        subtasks = json.loads(raw[start:end]) if start >= 0 else []
    except Exception as e:
        log.warn("jarvis_decompose_failed", error=str(e))
        subtasks = []

    # Step 2: If no subtasks, Jarvis answers directly
    if not subtasks:
        from intelligence.jarvis_core import think
        return await think(user_input, speak=speak, broadcast_fn=broadcast_fn)

    if broadcast_fn:
        await broadcast_fn({
            "type": "jarvis_dispatching",
            "session_id": session_id,
            "subtasks": [s.get("capability") for s in subtasks],
        })

    # Step 3: Dispatch subtasks
    task_ids = []
    for s in subtasks:
        capability = s.get("capability", "research")
        payload    = s.get("payload", {})
        task_id = await asyncio.to_thread(
            task_queue.enqueue, capability, payload, 3, session_id, TASK_TIMEOUT
        )
        task_ids.append(task_id)
        asyncio.create_task(dispatch(capability, task_id, payload, broadcast_fn))

    # Step 4: Poll for results
    deadline = time.time() + TASK_TIMEOUT
    results  = []
    while time.time() < deadline:
        done = []
        for tid in task_ids:
            res = await asyncio.to_thread(task_queue.get_results, tid)
            if res:
                done.append(res[0])
        if len(done) == len(task_ids):
            results = done
            break
        await asyncio.sleep(1)

    if not results:
        results = [{"summary": "Agent timed out — no result returned.", "success": False}]

    # Step 5: Synthesise
    summaries = "\n".join(
        f"[{r.get('agent_name', '?')}]: {r.get('summary', '')}" for r in results
    )
    synth_prompt = (
        f"Original request: {user_input}\n\n"
        f"Subagent results:\n{summaries}"
    )
    try:
        synth = await llm.complete(
            prompt=synth_prompt,
            system=_SYNTHESISE_SYSTEM,
            max_tokens=250,
        )
        response = synth.get("text", "").strip()
    except Exception as e:
        log.warn("jarvis_synthesise_failed", error=str(e))
        response = summaries[:300]

    log.info("jarvis_done", session=session_id, response_len=len(response))

    if speak:
        from intelligence.tts_engine import speak_async
        await speak_async(response)

    if broadcast_fn:
        await broadcast_fn({
            "type":     "jarvis_done",
            "session_id": session_id,
            "response": response,
            "results":  results,
        })

    return response
