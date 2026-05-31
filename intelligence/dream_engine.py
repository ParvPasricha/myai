"""
Dream Engine — generates synthetic tasks from unified memory.

Four strategies per session (5 tasks each = 20 total):
  remix        — blend 2 recent conversations into one hybrid scenario
  blend        — connect 2 unrelated domain facts and ask what links them
  edge_case    — take a work pattern and push it to its limit
  contradiction — invert a habit: what if Parv did the opposite?

Each task is a dict: {id, strategy, prompt, source_ids}
The evaluator runs each prompt through the LLM and scores it.
"""
import asyncio
import random
import time
import uuid
from typing import Optional

from intelligence import unified_memory
from intelligence.learning_engine import get_domain_summary
from observability.logger import log

_TASKS_PER_STRATEGY = 5


# ── Memory samplers ───────────────────────────────────────────────────────────

def _sample_conversations(n: int = 6) -> list[dict]:
    try:
        return unified_memory.recent_conversations(n)
    except Exception:
        return []


def _sample_collection(col_name: str, n: int = 10) -> list[dict]:
    try:
        col = unified_memory._col(col_name)
        if col.count() == 0:
            return []
        results = col.get(limit=n, include=["documents", "metadatas", "ids"])
        docs   = results.get("documents") or []
        metas  = results.get("metadatas") or []
        ids    = results.get("ids") or []
        return [{"id": i, "text": d, "metadata": m}
                for i, d, m in zip(ids, docs, metas)]
    except Exception:
        return []


# ── Strategy implementations ──────────────────────────────────────────────────

async def _remix_tasks(llm) -> list[dict]:
    convs = _sample_conversations(10)
    if len(convs) < 2:
        return []
    tasks = []
    for _ in range(_TASKS_PER_STRATEGY):
        a, b = random.sample(convs, 2)
        task_id = uuid.uuid4().hex[:8]
        prompt = (
            f"Two past interactions:\n\n"
            f"A: {a['text'][:300]}\n\n"
            f"B: {b['text'][:300]}\n\n"
            f"Synthesise a single insight or lesson that emerges from combining these two. "
            f"Be specific. What does someone who experienced both learn that they couldn't from either alone?"
        )
        tasks.append({
            "id": task_id,
            "strategy": "remix",
            "prompt": prompt,
            "source_ids": [a["id"], b["id"]],
        })
    return tasks


async def _blend_tasks(llm) -> list[dict]:
    facts = _sample_collection("intel_domain_knowledge", 12)
    if len(facts) < 2:
        return []
    tasks = []
    for _ in range(_TASKS_PER_STRATEGY):
        a, b = random.sample(facts, 2)
        task_id = uuid.uuid4().hex[:8]
        prompt = (
            f"Two pieces of knowledge from different domains:\n\n"
            f"A ({a['metadata'].get('domain','?')}): {a['text'][:250]}\n\n"
            f"B ({b['metadata'].get('domain','?')}): {b['text'][:250]}\n\n"
            f"What non-obvious connection exists between these? "
            f"How could one inform or improve the other? Give a concrete example."
        )
        tasks.append({
            "id": task_id,
            "strategy": "blend",
            "prompt": prompt,
            "source_ids": [a["id"], b["id"]],
        })
    return tasks


async def _edge_case_tasks(llm) -> list[dict]:
    patterns = _sample_collection("intel_work_patterns", 10)
    if not patterns:
        return []
    tasks = []
    for _ in range(_TASKS_PER_STRATEGY):
        p = random.choice(patterns)
        task_id = uuid.uuid4().hex[:8]
        prompt = (
            f"Work pattern observed:\n{p['text'][:300]}\n\n"
            f"What is the exact scenario where this pattern breaks down or fails catastrophically? "
            f"Describe the edge case, why it breaks, and what the recovery or prevention looks like."
        )
        tasks.append({
            "id": task_id,
            "strategy": "edge_case",
            "prompt": prompt,
            "source_ids": [p["id"]],
        })
    return tasks


async def _contradiction_tasks(llm) -> list[dict]:
    habits = _sample_collection("intel_habits", 10)
    if not habits:
        return []
    tasks = []
    for _ in range(_TASKS_PER_STRATEGY):
        h = random.choice(habits)
        task_id = uuid.uuid4().hex[:8]
        prompt = (
            f"Observed behaviour:\n{h['text'][:300]}\n\n"
            f"Construct the strongest possible argument for doing the exact opposite. "
            f"Under what conditions would the inverse be correct? "
            f"What would someone who consistently does the opposite know that makes it work for them?"
        )
        tasks.append({
            "id": task_id,
            "strategy": "contradiction",
            "prompt": prompt,
            "source_ids": [h["id"]],
        })
    return tasks


# ── Main generator ────────────────────────────────────────────────────────────

async def generate_session(session_id: str) -> list[dict]:
    """
    Generate 20 dream tasks (5 per strategy) from current memory.
    Returns list of task dicts ready for the evaluator.
    """
    from server.llm_router import llm

    strategies = [
        _remix_tasks,
        _blend_tasks,
        _edge_case_tasks,
        _contradiction_tasks,
    ]

    all_tasks: list[dict] = []
    for fn in strategies:
        try:
            tasks = await fn(llm)
            all_tasks.extend(tasks)
            log.info("dream_strategy_generated",
                     strategy=fn.__name__, count=len(tasks))
        except Exception as e:
            log.warn("dream_strategy_failed", strategy=fn.__name__, error=str(e))

    # Shuffle so evaluator doesn't process all of one type first
    random.shuffle(all_tasks)
    log.info("dream_session_generated", session=session_id, total=len(all_tasks))
    return all_tasks
