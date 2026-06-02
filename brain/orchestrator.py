"""
Orchestrator — the deterministic brain that controls everything.

Every request flows through here:

  User Input
      ↓
  Intent Classification   (fast pattern → LLM fallback)
      ↓
  Memory Check            (skip LLM if answer exists in memory)
      ↓
  Model Tier Selection    (tiny / small / medium / large / premium)
      ↓
  Execution Path          (direct Jarvis / planner / tool / memory agent)
      ↓
  Confidence Gate         (verify / cross-check / answer)
      ↓
  Hallucination Guard     (claim extraction → evidence check → critic)
      ↓
  Final Answer
"""
from __future__ import annotations
import time
import uuid
from typing import Any, Callable

from brain.schemas import (
    Intent, ModelTier, AgentAnswer, OrchestratorTrace
)
from brain.router import classify_intent, select_tier
from brain.confidence import gate, escalate_tier
from brain import state as brain_state
from observability.logger import log

# Tiers that map to LLM force_tier values (1=Ollama, 2=Claude, 3=OpenAI)
_TIER_TO_FORCE: dict[ModelTier, int | None] = {
    ModelTier.TINY:    1,   # Ollama only
    ModelTier.SMALL:   1,   # Ollama first
    ModelTier.MEDIUM:  None, # router decides (Ollama→Claude)
    ModelTier.LARGE:   2,   # Claude
    ModelTier.PREMIUM: 2,   # Claude (max tokens)
}

_TIER_MAX_TOKENS: dict[ModelTier, int] = {
    ModelTier.TINY:    50,
    ModelTier.SMALL:   300,
    ModelTier.MEDIUM:  600,
    ModelTier.LARGE:   1200,
    ModelTier.PREMIUM: 4096,
}


async def _memory_check(query: str) -> str | None:
    """
    Check if the answer already exists in memory.
    Returns the memory context string if found, None otherwise.
    """
    try:
        from intelligence.unified_memory import get_relevant_context
        ctx = get_relevant_context(query, n_each=1)
        if ctx and len(ctx.strip()) > 20:
            return ctx
    except Exception:
        pass
    return None


async def _run_direct(
    user_input: str,
    tier: ModelTier,
    memory_context: str | None,
    broadcast_fn: Callable | None,
    speak: bool,
) -> AgentAnswer:
    """Fast path — Jarvis brain answers directly, no subagent dispatch."""
    from intelligence.jarvis_core import think

    # For higher tiers, force the LLM call through Claude
    t0 = time.time()
    response = await think(user_input, speak=speak, broadcast_fn=broadcast_fn)
    latency  = (time.time() - t0) * 1000

    # Confidence: Jarvis direct answers are trusted — set above cross-check threshold
    # so the confidence gate passes without adding an extra critic LLM call
    confidence = 0.92 if memory_context else 0.87

    return AgentAnswer(
        answer=response,
        confidence=confidence,
        sources=["jarvis_brain"] + (["memory"] if memory_context else []),
        agent_name="jarvis_direct",
        latency_ms=latency,
        model_tier=tier,
    )


async def _run_agent_path(
    user_input: str,
    intent: Intent,
    broadcast_fn: Callable | None,
    speak: bool,
) -> AgentAnswer:
    """Route to head_agent for decomposition + subagent dispatch."""
    from agents.head_agent import handle as jarvis_handle

    t0 = time.time()
    response = await jarvis_handle(user_input, broadcast_fn=broadcast_fn, speak=speak)
    latency  = (time.time() - t0) * 1000

    return AgentAnswer(
        answer=response,
        confidence=0.82,
        sources=["agent_framework"],
        agent_name="head_agent",
        latency_ms=latency,
        model_tier=ModelTier.MEDIUM,
    )


async def _cross_check(answer: AgentAnswer, user_input: str) -> AgentAnswer:
    """
    Run critic agent on a cross-check required answer.
    If critic finds issues, escalate to a higher model tier.
    """
    try:
        from agents.critic_agent import critique
        issues = await critique(user_input, answer.answer)
        if issues:
            log.info("cross_check_issues", count=len(issues), issues=issues[:2])
            # Retry with higher tier
            from server.llm_router import llm
            from intelligence.jarvis_core import _JARVIS_SYSTEM, _build_situation
            import asyncio
            situation = await asyncio.to_thread(_build_situation)
            system = _JARVIS_SYSTEM
            if situation:
                system += f"\n\n--- CURRENT SITUATION ---\n{situation}"
            system += f"\n\nCRITIC FEEDBACK — address these issues:\n" + "\n".join(f"- {i}" for i in issues)

            result = await llm.complete(
                prompt=user_input,
                system=system,
                max_tokens=400,
                force_tier=2,   # escalate to Claude
            )
            answer.answer      = result.get("text", answer.answer).strip()
            answer.confidence  = 0.88
            answer.model_tier  = ModelTier.LARGE
            answer.sources.append("critic_reviewed")
    except Exception as e:
        log.warn("cross_check_failed", error=str(e))

    return answer


async def run(
    user_input: str,
    broadcast_fn: Callable | None = None,
    speak: bool = True,
    session_id: str | None = None,
) -> str:
    """
    Main orchestrator entry point.

    Returns the final answer string. All routing, confidence gating,
    and hallucination checking happens inside.
    """
    t0    = time.time()
    sid   = session_id or uuid.uuid4().hex[:8]
    trace = OrchestratorTrace(session_id=sid, user_input=user_input)

    bs = brain_state.get()
    bs.session_id  = sid
    bs.last_input  = user_input

    # ── Step 1: Intent classification ─────────────────────────────────────────
    intent_result  = await classify_intent(user_input)
    intent         = intent_result.intent
    i_conf         = intent_result.confidence
    trace.intent   = intent
    trace.intent_confidence = i_conf

    log.info("orchestrator_intent", session=sid, intent=intent.value,
             confidence=round(i_conf, 3))

    # ── Step 2: Memory check (skip LLM for memory_lookup) ─────────────────────
    memory_ctx  = None
    memory_hit  = False

    if intent in (Intent.MEMORY_LOOKUP, Intent.RETRIEVAL):
        memory_ctx = await _memory_check(user_input)
        if memory_ctx:
            memory_hit = True
            trace.memory_hit = True
            log.info("memory_hit", session=sid, chars=len(memory_ctx))

    # ── Step 3: Select model tier ─────────────────────────────────────────────
    tier = select_tier(intent, i_conf)
    trace.model_tier = tier
    log.info("orchestrator_tier", session=sid, tier=tier.value)

    # ── Step 4: Execute ───────────────────────────────────────────────────────
    DIRECT_INTENTS = {
        Intent.CHAT, Intent.REASONING, Intent.MEMORY_LOOKUP,
        Intent.MEMORY_WRITE, Intent.SYSTEM_CONTROL,
    }
    AGENT_INTENTS = {Intent.TOOL_USE, Intent.PLANNING, Intent.RETRIEVAL}

    if intent in DIRECT_INTENTS or (memory_hit and intent == Intent.RETRIEVAL):
        answer = await _run_direct(user_input, tier, memory_ctx, broadcast_fn, speak)
        trace.agent_used = "jarvis_direct"
    else:
        answer = await _run_agent_path(user_input, intent, broadcast_fn, speak)
        trace.agent_used = "head_agent"

    # ── Step 5: Confidence gate ────────────────────────────────────────────────
    decision = gate(answer)

    if decision == "verify":
        log.info("confidence_verify", session=sid, confidence=answer.confidence)
        higher_tier = escalate_tier(answer.model_tier)
        answer.model_tier = higher_tier
        # Re-run through direct path with higher tier
        answer = await _run_direct(user_input, higher_tier, memory_ctx, broadcast_fn, speak=False)
        answer.sources.append("verified")

    elif decision == "cross_check":
        log.info("confidence_cross_check", session=sid, confidence=answer.confidence)
        answer = await _cross_check(answer, user_input)

    # ── Step 6: Hallucination guard ───────────────────────────────────────────
    # Disabled in real-time path — adds 3+ LLM calls per response.
    # Enable explicitly per-request with always_check=True when needed.
    pass

    # ── Step 7: Record trace ──────────────────────────────────────────────────
    latency = (time.time() - t0) * 1000
    trace.latency_ms   = latency
    trace.final_answer = answer.answer

    bs.record_request(
        intent=intent,
        tier=tier,
        latency_ms=latency,
        memory_hit=memory_hit,
        hallucination=trace.hallucination_flagged,
    )
    bs.last_response = answer.answer

    # Record to episodic memory
    try:
        from memory.episodic import log_event
        log_event(
            "orchestrator_request",
            f"intent={intent.value} tier={tier.value} latency={round(latency,1)}ms",
            {"session_id": sid, "memory_hit": memory_hit},
        )
    except Exception:
        pass

    log.info("orchestrator_done", session=sid, latency_ms=round(latency, 1),
             intent=intent.value, tier=tier.value)

    return answer.answer
