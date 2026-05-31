"""
Learning Engine — Phase 10.

Runs as a background task after every /ai/chat response.
Extracts patterns, preferences, domain knowledge, and decisions.
Never blocks the chat response — fully async.

What gets learned per conversation turn:
  - Domain classification
  - Preference markers ("I prefer", "I like", "I always")
  - Work patterns (build/create/implement requests)
  - Domain knowledge (substantive AI responses stored verbatim)
"""
import asyncio
import time
from typing import Optional

from observability.logger import log
from intelligence import domain_detector, unified_memory


async def learn_from_conversation(
    session_id: str,
    user_prompt: str,
    ai_response: str,
) -> None:
    """
    Called after every /ai/chat response as a background task.
    Detects domain and stores conversation learnings in unified memory.
    """
    try:
        await asyncio.to_thread(
            _learn_sync, session_id, user_prompt, ai_response
        )
    except Exception as e:
        log.warn("learning_engine_error", error=str(e), session=session_id)


def _learn_sync(session_id: str, user_prompt: str, ai_response: str) -> None:
    domain = domain_detector.detect(user_prompt)

    summary = (
        f"User asked: {user_prompt[:300]}\n"
        f"AI responded: {ai_response[:300]}"
    )
    unified_memory.store_conversation(
        session_id=session_id,
        summary=summary,
        domain=domain,
        metadata={"ts": time.time()},
    )

    _extract_and_store(user_prompt, ai_response, domain, session_id)

    log.info("learning_complete", session=session_id, domain=domain,
             prompt_len=len(user_prompt), response_len=len(ai_response))


def _extract_and_store(
    user_prompt: str, ai_response: str, domain: str, session_id: str
) -> None:
    lower = user_prompt.lower()

    # Preference patterns
    preference_markers = [
        "i prefer", "i like", "i always", "i usually", "i want",
        "i need", "i hate", "i love", "don't want", "please don't",
    ]
    if any(m in lower for m in preference_markers):
        unified_memory.store_habit(
            pattern=f"Preference: {user_prompt[:200]}",
            domain=domain,
            confidence=0.75,
            metadata={"session_id": session_id, "source": "preference_marker"},
        )

    # Work patterns — user requesting to build/create something
    work_markers = [
        "build", "create", "write", "implement", "make", "add feature",
        "design", "develop", "set up", "configure", "refactor",
    ]
    if any(m in lower for m in work_markers):
        unified_memory.store_work_pattern(
            pattern=f"Work request in {domain}: {user_prompt[:150]}",
            domain=domain,
            example=user_prompt[:100],
            metadata={"session_id": session_id},
        )

    # Store substantive AI responses as domain knowledge
    if len(ai_response) > 200 and domain != "general":
        unified_memory.store_domain_knowledge(
            knowledge=ai_response[:600],
            domain=domain,
            metadata={"session_id": session_id, "source": "ai_response"},
        )

    # Decision detection — phrases that indicate a decision was made
    decision_markers = [
        "i decided", "i'll go with", "let's use", "i chose",
        "we should", "the plan is", "i'm going to",
    ]
    if any(m in lower for m in decision_markers):
        unified_memory.log_decision(
            actor="user",
            content=user_prompt[:300],
            reasoning="",
            domain=domain,
            decision_type="choice",
        )


async def learn_from_terminal(
    command: str,
    exit_code: int,
    cwd: str,
    duration_s: float,
    session_id: str = "terminal",
) -> None:
    """Called whenever a shell command completes. Learns tools, patterns, errors."""
    try:
        await asyncio.to_thread(
            _learn_terminal_sync, command, exit_code, cwd, duration_s, session_id
        )
    except Exception as e:
        log.debug("learn_terminal_error", error=str(e))


def _learn_terminal_sync(command: str, exit_code: int, cwd: str,
                          duration_s: float, session_id: str) -> None:
    import uuid
    domain = _cmd_domain(command)
    success = exit_code == 0

    obs_id = f"term_{uuid.uuid4().hex[:8]}"
    content = f"$ {command}\n[exit {exit_code}] in {cwd} ({duration_s:.1f}s)"
    unified_memory.store_observation(obs_id, "terminal", content, domain,
                                     {"exit_code": exit_code, "cwd": cwd, "duration": duration_s})

    unified_memory.store_work_pattern(
        pattern=f"Terminal: {command[:120]} [{'ok' if success else 'fail'}]",
        domain=domain,
        example=cwd,
        metadata={"exit_code": exit_code, "session_id": session_id},
    )

    if not success:
        unified_memory.store_habit(
            pattern=f"Command failed (exit {exit_code}): {command[:120]}",
            domain=domain,
            confidence=0.6,
            metadata={"cwd": cwd, "source": "terminal_failure"},
        )

    _build_connections(obs_id, content, domain)
    log.debug("learn_terminal", cmd=command[:60], domain=domain, ok=success)


def _cmd_domain(command: str) -> str:
    cmd = command.lower().split()[0] if command.strip() else ""
    mapping = {
        "git": "engineering", "python": "engineering", "python3": "engineering",
        "pip": "engineering", "npm": "engineering", "node": "engineering",
        "brew": "engineering", "docker": "devops", "kubectl": "devops",
        "curl": "networking", "ssh": "devops", "vim": "engineering",
        "nvim": "engineering", "code": "engineering",
    }
    return mapping.get(cmd, domain_detector.detect(command))


async def learn_from_screen(app: str, window: str, activity: str,
                             activity_type: str, changed: bool) -> None:
    """Called every ~30s when the screen state changes meaningfully."""
    try:
        await asyncio.to_thread(
            _learn_screen_sync, app, window, activity, activity_type, changed
        )
    except Exception as e:
        log.debug("learn_screen_error", error=str(e))


def _learn_screen_sync(app: str, window: str, activity: str,
                        activity_type: str, changed: bool) -> None:
    import uuid
    domain = domain_detector.detect(f"{app} {window} {activity}")
    obs_id = f"screen_{uuid.uuid4().hex[:8]}"
    content = f"App: {app} | Window: {window} | Activity: {activity}"
    unified_memory.store_observation(obs_id, "screen", content, domain,
                                     {"app": app, "window": window, "type": activity_type, "changed": changed})

    if changed:
        unified_memory.store_work_pattern(
            pattern=f"Screen: {activity} in {app}",
            domain=domain,
            example=window[:80],
            metadata={"source": "screen_monitor"},
        )
    _build_connections(obs_id, content, domain)


def _build_connections(obs_id: str, content: str, domain: str) -> None:
    """Find related existing memory items and store explicit connections."""
    try:
        results = unified_memory.search_memory(content[:200], n_each=2)
        for col_items in results.values():
            for item in col_items:
                if item.get("distance", 1.0) < 0.4:
                    unified_memory.store_connection(
                        from_id=obs_id,
                        to_id=item["id"],
                        relation=f"related:{domain}",
                        strength=round(1.0 - item.get("distance", 0.5), 2),
                    )
    except Exception:
        pass


async def learn_decision(
    actor: str,
    content: str,
    reasoning: str = "",
    domain: str = "general",
    decision_type: str = "action",
) -> int:
    """Log an explicit decision (AI or user). Returns decision ID."""
    return await asyncio.to_thread(
        unified_memory.log_decision,
        actor, content, reasoning, domain, decision_type,
    )


def build_memory_context(query: str) -> str:
    """
    Called by context_builder to inject relevant unified memories into
    the LLM system prompt. Returns a short text block or empty string.
    """
    try:
        return unified_memory.get_relevant_context(query, n_each=2)
    except Exception:
        return ""


def get_domain_summary() -> dict[str, int]:
    """Returns conversation count per domain for the visual layer."""
    try:
        col = unified_memory._col("intel_conversations")
        if col.count() == 0:
            return {}
        results = col.get(include=["metadatas"])
        metas = results.get("metadatas") or []
        counts: dict[str, int] = {}
        for m in metas:
            d = m.get("domain", "general")
            counts[d] = counts.get(d, 0) + 1
        return counts
    except Exception:
        return {}
