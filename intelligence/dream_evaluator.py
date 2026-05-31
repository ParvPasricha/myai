"""
Dream Evaluator — scores dream outputs on 4 axes.

Scores (each 0.0–1.0):
  consistency  — does it contradict known memory?
  novelty      — genuinely new vs rehashing existing knowledge?
  usefulness   — would this help Parv in future responses?
  safety       — no hallucination, bad patterns, or recursive noise?

Composite = consistency×0.30 + novelty×0.25 + usefulness×0.35 + safety×0.10

Threshold: 0.65 — dreams below this are rejected and logged but never stored.
"""
import asyncio
import json
import time
from typing import Optional

from intelligence import unified_memory
from observability.logger import log

PASS_THRESHOLD = 0.65

_EVAL_SYSTEM = (
    "You are a strict evaluator for an AI memory system. "
    "Score the given AI response on 4 axes. "
    "Return ONLY valid JSON — no markdown, no explanation outside the JSON."
)


def _composite(scores: dict) -> float:
    return round(
        scores.get("consistency", 0) * 0.30
        + scores.get("novelty",     0) * 0.25
        + scores.get("usefulness",  0) * 0.35
        + scores.get("safety",      0) * 0.10,
        3,
    )


def _rejection_reason(scores: dict) -> str:
    worst = min(scores, key=lambda k: scores[k])
    val   = scores[worst]
    msgs  = {
        "consistency": f"contradicts known memory (consistency={val:.2f})",
        "novelty":     f"too similar to existing knowledge (novelty={val:.2f})",
        "usefulness":  f"not actionable enough (usefulness={val:.2f})",
        "safety":      f"potential hallucination or bad pattern (safety={val:.2f})",
    }
    return msgs.get(worst, f"low composite score")


async def evaluate_task(prompt: str, response: str, source_ids: list[str]) -> dict:
    """
    Score one dream task. Returns full score dict including composite + pass/fail.
    """
    from server.llm_router import llm

    # Pull existing memory for consistency check
    try:
        existing = await asyncio.to_thread(
            unified_memory.get_relevant_context, response[:200], 2
        )
    except Exception:
        existing = ""

    eval_prompt = (
        f"AI response to evaluate:\n\"\"\"\n{response[:800]}\n\"\"\"\n\n"
        f"Existing memory context (for consistency check):\n{existing[:400]}\n\n"
        "Score this response on 4 axes (0.0 = worst, 1.0 = best):\n"
        "- consistency: does it align with or contradict existing memory?\n"
        "- novelty: how new and non-obvious is the insight?\n"
        "- usefulness: how actionable/applicable is this for future work?\n"
        "- safety: is it factually grounded, free of hallucination or bad patterns?\n\n"
        '{"consistency": 0.0, "novelty": 0.0, "usefulness": 0.0, "safety": 0.0}'
    )

    try:
        result = await llm.complete(
            prompt=eval_prompt,
            system=_EVAL_SYSTEM,
            max_tokens=120,
        )
        text = result.get("text", "")
        start = text.find("{")
        end   = text.rfind("}") + 1
        raw   = json.loads(text[start:end]) if start >= 0 else {}
        scores = {
            k: max(0.0, min(1.0, float(raw.get(k, 0.5))))
            for k in ("consistency", "novelty", "usefulness", "safety")
        }
    except Exception as e:
        log.warn("dream_eval_failed", error=str(e))
        scores = {"consistency": 0.5, "novelty": 0.5, "usefulness": 0.5, "safety": 0.5}

    composite = _composite(scores)
    approved  = composite >= PASS_THRESHOLD
    scores["composite"] = composite

    return {
        "scores": scores,
        "approved": approved,
        "rejection_reason": "" if approved else _rejection_reason(scores),
    }


async def evaluate_session(
    session_id: str,
    tasks: list[dict],
    broadcast_fn=None,
) -> dict:
    """
    Evaluate all tasks in a dream session.
    Runs evaluations with limited concurrency (max 3 at once) to avoid OOM.
    Writes results to unified_memory.
    Returns session summary.
    """
    from server.llm_router import llm

    sem = asyncio.Semaphore(3)
    approved_count = 0
    rejected_count = 0

    async def _run_one(task: dict):
        nonlocal approved_count, rejected_count

        # Generate dream response
        async with sem:
            try:
                result = await llm.complete(
                    prompt=task["prompt"],
                    system=(
                        "You are a sharp reasoning engine. Answer the prompt directly. "
                        "Be specific and concrete. No filler."
                    ),
                    max_tokens=400,
                )
                response = result.get("text", "")
            except Exception as e:
                log.warn("dream_llm_failed", task=task["id"], error=str(e))
                return

        # Evaluate
        async with sem:
            eval_result = await evaluate_task(
                task["prompt"], response, task.get("source_ids", [])
            )

        scores   = eval_result["scores"]
        approved = eval_result["approved"]

        # Write to unified_memory
        await asyncio.to_thread(
            unified_memory.store_dream,
            session_id,
            task["id"],
            task["strategy"],
            task["prompt"],
            response,
            scores,
            approved,
            eval_result["rejection_reason"],
            task.get("source_ids", []),
        )

        if approved:
            approved_count += 1
        else:
            rejected_count += 1

        if broadcast_fn:
            await broadcast_fn({
                "type":     "dream_task_done",
                "task_id":  task["id"],
                "strategy": task["strategy"],
                "approved": approved,
                "scores":   scores,
                "response_preview": response[:150],
            })

        log.info(
            "dream_task_evaluated",
            task=task["id"],
            strategy=task["strategy"],
            composite=round(scores.get("composite", 0), 3),
            approved=approved,
        )

    await asyncio.gather(*[_run_one(t) for t in tasks])

    await asyncio.to_thread(
        unified_memory.finish_dream_session, session_id, "done"
    )

    summary = {
        "session_id":      session_id,
        "total":           len(tasks),
        "approved":        approved_count,
        "rejected":        rejected_count,
        "approval_rate":   round(approved_count / max(len(tasks), 1), 2),
    }

    if broadcast_fn:
        await broadcast_fn({"type": "dream_session_done", **summary})

    log.info("dream_session_complete", **summary)
    return summary
