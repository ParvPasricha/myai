"""
Context builder — assembles a personalised ~2000-token context block
injected at the top of every LLM prompt.

Layers (in order of freshness):
  1. Working memory   — last N messages of the current session (Redis)
  2. Semantic memory  — top-3 relevant summaries/facts from ChromaDB
  3. Structured facts — active goals, recent decisions, item queries
  4. Brain State      — current focus/energy/stress/activity

This is the module that makes the AI feel like it knows you.
"""
import time
from typing import Any

from intelligence import brain_state as bs
from memory import working, episodic, semantic, structured


_MAX_CHARS = 2000


def build(query: str, session_id: str | None = None) -> str:
    """
    Build a context block for the given user query.
    Returns a string to prepend to the LLM system prompt.
    """
    parts: list[str] = []

    # 1. Brain State
    state = bs.get()
    parts.append(
        f"[CURRENT STATE] Focus:{state.get('focus')}/10 "
        f"Energy:{state.get('energy')}/10 "
        f"Stress:{state.get('stress')}/10 "
        f"Activity:{state.get('current_activity')} "
        f"Location:{state.get('location')}"
    )

    # 2. Working memory (last session turns)
    sid = session_id or working.current_session()
    ctx = working.get_context_block(sid, max_chars=800)
    if ctx:
        parts.append(f"[RECENT CONVERSATION]\n{ctx}")

    # 3. Semantic search — summaries and facts relevant to this query
    try:
        semantic_hits = semantic.search_all(query, n_each=2)
        if semantic_hits:
            items = [f"- {h['text'][:150]}" for h in semantic_hits[:4]]
            parts.append("[RELEVANT MEMORIES]\n" + "\n".join(items))
    except Exception:
        pass

    # 4. Active goals
    try:
        goals = structured.get_active_goals()
        if goals:
            goal_lines = [f"- {g['description']}" for g in goals[:3]]
            parts.append("[YOUR GOALS]\n" + "\n".join(goal_lines))
    except Exception:
        pass

    # 5. Recent decisions (last 3 days)
    try:
        decisions = structured.get_decisions(days=3)
        if decisions:
            dec_lines = [f"- {d['description']}" for d in decisions[:3]]
            parts.append("[RECENT DECISIONS]\n" + "\n".join(dec_lines))
    except Exception:
        pass

    block = "\n\n".join(parts)

    # Hard cap — truncate from the middle to preserve recency + state
    if len(block) > _MAX_CHARS:
        head = block[:600]
        tail = block[-(_MAX_CHARS - 600):]
        block = head + "\n...[truncated]...\n" + tail

    return block


def build_system_prompt(query: str, session_id: str | None = None,
                        base_system: str = "You are PARV-AI, a personal AI assistant.") -> str:
    """Return a complete system prompt with context injected."""
    ctx = build(query, session_id)
    if ctx:
        return f"{base_system}\n\n{ctx}"
    return base_system
