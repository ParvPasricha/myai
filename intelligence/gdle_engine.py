"""
Guided Dream Learning Engine (GDLE)

Structured deep-learning sessions triggered manually with a specific topic.

Flow per session:
  1. Concept map  — break topic into 6–8 ordered subtopics
  2. Derivation   — first-principles step-by-step reasoning per subtopic
  3. Problems     — 3 practice problems (easy/medium/hard) per subtopic
  4. Critique     — LLM critic scores each derivation on 3 axes
  5. Guide        — final personalized learning guide

Depth levels: beginner | intermediate | advanced | expert
"""
import asyncio
import json
import time

from intelligence import unified_memory
from observability.logger import log

_DEPTHS = {
    "beginner":     "Assume no prior knowledge. Use intuition over formalism. Simple language.",
    "intermediate": "Assume basic domain familiarity. Introduce formal notation where it helps.",
    "advanced":     "Assume solid domain knowledge. Include edge cases, failure modes, tradeoffs.",
    "expert":       "Peer-level depth. First principles, mathematical rigor, links to cutting-edge work.",
}

_CRITIC_SYSTEM = (
    "You are a rigorous academic critic. Find flaws. Score only. "
    "No encouragement, no padding. Return ONLY valid JSON."
)


async def _concept_map(llm, topic: str, depth: str, style: str, constraints: str) -> list[str]:
    depth_hint = _DEPTHS.get(depth, _DEPTHS["intermediate"])
    extras = ""
    if style:
        extras += f"\nPreferred style: {style}"
    if constraints:
        extras += f"\nConstraints: {constraints}"

    prompt = (
        f"Topic: {topic}\nDepth: {depth} — {depth_hint}{extras}\n\n"
        f"Break this topic into 6–8 essential subtopics forming a complete learning path. "
        f"Order them logically — prerequisites first. "
        f"Return ONLY a JSON array of strings, no other text."
    )
    result = await llm.complete(
        prompt=prompt,
        system="Return ONLY valid JSON arrays. No text outside the JSON.",
        max_tokens=300,
    )
    text = result.get("text", "")
    try:
        start = text.find("[")
        end   = text.rfind("]") + 1
        items = json.loads(text[start:end])
        return [s for s in items if isinstance(s, str)][:8]
    except Exception:
        lines = [l.strip("- •*0123456789. \t") for l in text.splitlines() if l.strip()]
        return [l for l in lines if l][:8]


async def _derive(llm, topic: str, subtopic: str, depth: str, style: str,
                  prior_critique: str = "") -> str:
    depth_hint = _DEPTHS.get(depth, _DEPTHS["intermediate"])
    style_line = f"Style: {style}\n" if style else ""
    critique_line = (
        f"\nPrevious critique to address in this attempt:\n{prior_critique}\n"
        if prior_critique else ""
    )
    prompt = (
        f"Context topic: {topic}\nSubtopic: {subtopic}\nDepth: {depth} — {depth_hint}\n"
        f"{style_line}{critique_line}\n"
        f"Derive this subtopic from first principles using numbered steps. "
        f"Each step must build on the last. Start from the most basic assumption. "
        f"End at complete understanding. No vague gestures — be concrete."
    )
    result = await llm.complete(
        prompt=prompt,
        system="You are a rigorous teacher. Derive from first principles. Be specific and step-by-step.",
        max_tokens=600,
    )
    return result.get("text", "")


async def _problems(llm, topic: str, subtopic: str, derivation: str, depth: str) -> list[dict]:
    prompt = (
        f"Topic: {topic} — Subtopic: {subtopic}\n\n"
        f"Key concepts:\n{derivation[:400]}\n\n"
        f"Generate exactly 3 practice problems: easy, medium, hard. "
        f"For each: problem statement, expected approach (not solution), and common mistake learners make. "
        f'Return ONLY valid JSON: [{{"difficulty":"easy","problem":"...","approach":"...","common_mistake":"..."}}, ...]'
    )
    result = await llm.complete(
        prompt=prompt,
        system="Return ONLY valid JSON arrays. No text outside the JSON.",
        max_tokens=500,
    )
    text = result.get("text", "")
    try:
        start = text.find("[")
        end   = text.rfind("]") + 1
        items = json.loads(text[start:end])
        return [p for p in items if isinstance(p, dict)][:3]
    except Exception:
        return []


async def _critique(llm, subtopic: str, derivation: str) -> dict:
    prompt = (
        f'Derivation for "{subtopic}":\n"""\n{derivation[:800]}\n"""\n\n'
        f"Score on 3 axes (0.0=worst, 1.0=best):\n"
        f"- correctness: is the reasoning factually sound and logically valid?\n"
        f"- clarity: would a target learner follow each step without confusion?\n"
        f"- depth: does it build real understanding vs listing facts?\n\n"
        f"Also provide one specific critique (weakest point, no padding).\n\n"
        f'{{"correctness":0.0,"clarity":0.0,"depth":0.0,"critique":"..."}}'
    )
    result = await llm.complete(prompt=prompt, system=_CRITIC_SYSTEM, max_tokens=200)
    text = result.get("text", "")
    try:
        start = text.find("{")
        end   = text.rfind("}") + 1
        raw   = json.loads(text[start:end])
        return {
            "correctness": max(0.0, min(1.0, float(raw.get("correctness", 0.5)))),
            "clarity":     max(0.0, min(1.0, float(raw.get("clarity",     0.5)))),
            "depth":       max(0.0, min(1.0, float(raw.get("depth",       0.5)))),
            "critique":    str(raw.get("critique", "")),
        }
    except Exception:
        return {"correctness": 0.5, "clarity": 0.5, "depth": 0.5, "critique": ""}


async def _build_guide(llm, topic: str, depth: str, concepts: list[dict]) -> str:
    summary = "\n".join(
        f"- {c['subtopic']} (score {c['score']:.2f}): {c['derivation'][:180]}..."
        for c in concepts
    )
    prompt = (
        f"Topic: {topic}\nDepth: {depth}\n\nSubtopics covered:\n{summary}\n\n"
        f"Write a personalized learning guide:\n"
        f"1. Recommended study order with reasoning\n"
        f"2. Single most important insight per subtopic\n"
        f"3. Three common misconceptions to avoid\n"
        f"4. What mastery of this topic enables\n"
        f"5. Suggested next topics after this one\n\n"
        f"Direct and actionable. No filler. Tailored to a {depth} learner."
    )
    result = await llm.complete(
        prompt=prompt,
        system="Write direct, actionable learning guides. No padding. No motivational language.",
        max_tokens=700,
    )
    return result.get("text", "")


async def run_gdle_session(
    session_id: str,
    topic: str,
    depth: str = "intermediate",
    style: str = "",
    constraints: str = "",
    broadcast_fn=None,
) -> dict:
    """
    Run a full GDLE session. Stores results in SQLite.
    Broadcasts live updates via WebSocket if broadcast_fn is provided.
    Returns session summary dict.
    """
    from server.llm_router import llm

    if broadcast_fn:
        await broadcast_fn({"type": "gdle_start", "session_id": session_id, "topic": topic})

    # Phase 1: Concept map
    log.info("gdle_phase1", session=session_id, topic=topic)
    try:
        subtopics = await _concept_map(llm, topic, depth, style, constraints)
    except Exception as e:
        log.error("gdle_concept_map_failed", error=str(e))
        subtopics = [topic]

    if not subtopics:
        subtopics = [topic]

    if broadcast_fn:
        await broadcast_fn({"type": "gdle_concept_map", "subtopics": subtopics})

    log.info("gdle_concept_map_done", count=len(subtopics))

    # Phases 2–4: per subtopic, max 2 concurrent
    sem = asyncio.Semaphore(2)
    concepts: list[dict] = []
    _PASS_THRESHOLD = 0.70
    _MAX_RETRIES = 2

    async def _process(subtopic: str, idx: int) -> dict | None:
        concept_id = f"{session_id}_{idx}"
        try:
            async with sem:
                derivation = await _derive(llm, topic, subtopic, depth, style)
            async with sem:
                crit = await _critique(llm, subtopic, derivation)

            score = round(
                crit["correctness"] * 0.4 + crit["clarity"] * 0.3 + crit["depth"] * 0.3, 3
            )

            for attempt in range(_MAX_RETRIES):
                if score >= _PASS_THRESHOLD:
                    break
                log.info("gdle_rederiving", subtopic=subtopic, attempt=attempt + 1, score=score)
                async with sem:
                    derivation = await _derive(
                        llm, topic, subtopic, depth, style,
                        prior_critique=crit.get("critique", ""),
                    )
                async with sem:
                    crit = await _critique(llm, subtopic, derivation)
                score = round(
                    crit["correctness"] * 0.4 + crit["clarity"] * 0.3 + crit["depth"] * 0.3, 3
                )

            async with sem:
                probs = await _problems(llm, topic, subtopic, derivation, depth)
            concept = {
                "id":         concept_id,
                "session_id": session_id,
                "subtopic":   subtopic,
                "derivation": derivation,
                "problems":   probs,
                "critique":   crit,
                "score":      score,
                "ts":         time.time(),
            }
            await asyncio.to_thread(unified_memory.store_gdle_concept, concept)

            if broadcast_fn:
                await broadcast_fn({
                    "type":             "gdle_concept_done",
                    "concept_id":       concept_id,
                    "subtopic":         subtopic,
                    "score":            score,
                    "problems_count":   len(probs),
                    "critique_preview": crit.get("critique", "")[:150],
                })

            log.info("gdle_concept_done", subtopic=subtopic, score=score)
            return concept
        except Exception as e:
            log.warn("gdle_concept_failed", subtopic=subtopic, error=str(e))
            return None

    results = await asyncio.gather(*[_process(st, i) for i, st in enumerate(subtopics)])
    concepts = [c for c in results if c is not None]

    # Phase 5: Learning guide
    if broadcast_fn:
        await broadcast_fn({"type": "gdle_guide_start"})

    try:
        guide = await _build_guide(llm, topic, depth, concepts)
    except Exception as e:
        log.warn("gdle_guide_failed", error=str(e))
        guide = ""

    avg_score = round(sum(c["score"] for c in concepts) / max(len(concepts), 1), 3)
    await asyncio.to_thread(
        unified_memory.finish_gdle_session, session_id, "done", avg_score, guide
    )

    summary = {
        "session_id":    session_id,
        "topic":         topic,
        "depth":         depth,
        "subtopics":     subtopics,
        "concepts_count": len(concepts),
        "avg_score":     avg_score,
    }

    if broadcast_fn:
        await broadcast_fn({"type": "gdle_done", **summary, "guide": guide})

    log.info("gdle_session_complete", session=session_id, topic=topic, avg_score=avg_score)
    return summary
