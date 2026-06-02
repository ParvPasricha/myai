"""
Memory Manager — unified get_context() for the orchestrator.

Assembles context from all three memory layers in priority order:
  1. Working memory   — current session turns (most recent, highest weight)
  2. Episodic memory  — recent events relevant to the query
  3. Semantic memory  — vector-searched facts and summaries

Semantic is NOT injected wholesale — only the top-k most relevant chunks,
to avoid cross-session hallucination (confirmed issue in prior architecture).
"""
from __future__ import annotations
import time
from observability.logger import log


def get_context(query: str, session_id: str | None = None) -> str:
    """
    Assemble a context block for a given query.

    Returns a structured string ready for injection into an LLM prompt.
    Empty sections are omitted.
    """
    parts: list[str] = []

    # ── 1. Working memory — current session ───────────────────────────────────
    try:
        from memory import working
        sid = session_id or working.current_session()
        ctx = working.get_context_block(sid, max_chars=800)
        if ctx:
            parts.append(f"[WORKING MEMORY — current session]\n{ctx}")
    except Exception as e:
        log.warn("memory_manager_working_failed", error=str(e))

    # ── 2. Episodic — recent relevant events ──────────────────────────────────
    try:
        from memory.episodic import search
        events = search(query, limit=3)
        if events:
            lines = []
            for ev in events:
                ts = time.strftime("%Y-%m-%d", time.localtime(ev.get("timestamp", 0)))
                lines.append(f"  [{ts}] {ev.get('content', ev.get('description', ''))[:120]}")
            parts.append("[EPISODIC MEMORY — relevant past events]\n" + "\n".join(lines))
    except Exception as e:
        log.warn("memory_manager_episodic_failed", error=str(e))

    # ── 3. Semantic — top-k relevant facts ───────────────────────────────────
    try:
        from memory.semantic import search as sem_search
        results = sem_search(query, collection="parv_facts", top_k=2)
        if results:
            lines = [f"  • {r['document'][:100]}" for r in results if r.get("document")]
            if lines:
                parts.append("[SEMANTIC MEMORY — relevant facts]\n" + "\n".join(lines))
    except Exception as e:
        log.warn("memory_manager_semantic_failed", error=str(e))

    if not parts:
        return ""

    return "\n\n".join(parts)


def write_fact(fact: str, confidence: float = 0.9, source: str = "user") -> None:
    """Persist a fact to semantic memory with metadata."""
    try:
        from memory.semantic import store
        store(
            text=fact,
            collection="parv_facts",
            metadata={"confidence": confidence, "source": source, "ts": time.time()},
        )
        log.info("memory_manager_fact_written", fact=fact[:60], confidence=confidence)
    except Exception as e:
        log.warn("memory_manager_write_failed", error=str(e))


def write_event(event_type: str, description: str, outcome: str = "") -> None:
    """Log an event to episodic memory."""
    try:
        from memory.episodic import log_event
        log_event(event_type, description, {"outcome": outcome} if outcome else None)
        log.info("memory_manager_event_logged", type=event_type)
    except Exception as e:
        log.warn("memory_manager_event_failed", error=str(e))
