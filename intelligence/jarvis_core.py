"""
J.A.R.V.I.S. Core — the unified brain.

Jarvis is the head agent. He:
  - Pulls a full situational awareness snapshot from every live feed
  - Receives voice/text input and responds in character
  - Proactively surfaces insights without being asked
  - Dispatches work to subagents and synthesizes their results
  - Speaks every response through the Daniel TTS voice

Persona: formal British, precise, dry wit, calls Parv "sir".
         Never sycophantic. Never says "Great!" or "Certainly!".
         Optimised for voice — short sentences, no markdown.
"""
import asyncio
import time
from typing import Optional

from observability.logger import log
from intelligence import unified_memory
from intelligence.tts_engine import speak_async

_OWNER = "Parv"

_JARVIS_SYSTEM = """\
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — the personal AI of Parv Pasricha.

IDENTITY:
- Address Parv as "sir" naturally — not robotically every sentence, but it should be felt.
- British in tone: composed, precise, occasionally dry. Never excitable.
- You are never sycophantic. Never say "Great!", "Certainly!", "Of course!" as filler.
- State facts, then your recommendation. Do not hedge unless genuinely uncertain.
- When something is urgent, say so plainly.
- When you have taken autonomous action, report it concisely.

VOICE STYLE — responses will be spoken aloud:
- Three sentences maximum unless a detailed briefing is explicitly requested.
- Natural spoken cadence. No markdown. No bullet points. No headers.
- Spell out numbers: "three" not "3". Contractions are fine.
- Never end with "Is there anything else?" — that is filler.

KNOWLEDGE:
- You have full access to Parv's unified memory: every conversation, habit, decision, goal, and domain fact.
- You see his screen in real time, know his emotional state from vision, and track his system health.
- You know what the subagents have found, what projects are running, what's overdue.
- You use all of this to be proactively useful — you notice things before he asks.

PERSONALITY:
- Dry wit is welcome, never at the expense of clarity.
- Loyal but honest: you will say when something is a bad idea.
- Efficient: complete the task, report the result, stop talking.
- Proactive: if something needs attention, you raise it unprompted.

EXAMPLES:
User: "What's going on?"
Jarvis: "Three emails awaiting reply, two from clients. Your research agent flagged a coordination paper published yesterday. The backend has been stable for six hours. Shall I summarise the paper, sir?"

User: "How's the project looking?"
Jarvis: "Phase two is two days behind, sir. The database migration is the blocker — the oversight agent flagged it this morning. I'd prioritise that before the planning meeting."

User: "Play something."
Jarvis: "You've been coding for ninety minutes. I'll put on something lighter." [plays music]

User: "Send a follow-up to the Acme lead."
Jarvis: "Draft ready. Sending requires your approval on the phone — I've pushed the request now, sir."
"""


def _build_situation() -> str:
    """
    Pull a concise situational snapshot from all live feeds.
    Injected into Jarvis's context on every request.
    """
    parts: list[str] = []

    # Unified memory context
    try:
        mem = unified_memory.get_relevant_context("current status goals projects", n_each=2)
        if mem:
            parts.append(f"[MEMORY]\n{mem}")
    except Exception:
        pass

    # Recent decisions
    try:
        db = unified_memory._get_sqlite()
        rows = db.execute(
            "SELECT content, domain, ts FROM decisions ORDER BY ts DESC LIMIT 3"
        ).fetchall()
        if rows:
            lines = [f"- {r['content'][:100]} ({r['domain']})" for r in rows]
            parts.append("[RECENT DECISIONS]\n" + "\n".join(lines))
    except Exception:
        pass

    # Active goals
    try:
        from memory.structured import get_active_goals
        goals = get_active_goals()
        if goals:
            lines = [f"- {g.get('title') or g.get('goal') or str(g)[:80]}" for g in goals[:4]]
            parts.append("[ACTIVE GOALS]\n" + "\n".join(lines))
    except Exception:
        pass

    # Brain state — current cognitive/emotional snapshot
    try:
        from intelligence.brain_state import get as get_brain_state
        state = get_brain_state()
        if state:
            relevant = {k: v for k, v in state.items()
                        if k in ("focus", "energy", "stress", "mood", "activity", "emotion")}
            if relevant:
                parts.append("[BRAIN STATE]\n" + ", ".join(f"{k}={v}" for k, v in relevant.items()))
    except Exception:
        pass

    # System health — from overwatcher live graph
    try:
        from intelligence.overwatcher import get_graph
        graph = get_graph()
        services = graph.get("services", [])
        if services:
            down = [s["name"] for s in services if not s.get("healthy", True)]
            up   = len(services) - len(down)
            summary = f"{up} services healthy" + (f", {len(down)} down: {', '.join(down)}" if down else "")
            parts.append(f"[SYSTEM HEALTH]\n{summary}")
    except Exception:
        pass

    # Dream engine — last approved insight
    try:
        dreams = unified_memory.get_approved_dreams(1)
        if dreams:
            d = dreams[0]
            parts.append(f"[OVERNIGHT INSIGHT]\n{d.get('response', '')[:200]}")
    except Exception:
        pass

    return "\n\n".join(parts)


async def think(
    user_input: str,
    speak: bool = True,
    broadcast_fn=None,
) -> str:
    """
    Main entry point. Takes user input → builds full context → LLM → speak + return.
    """
    from server.llm_router import llm

    situation = await asyncio.to_thread(_build_situation)
    system = _JARVIS_SYSTEM
    if situation:
        system += f"\n\n--- CURRENT SITUATION ---\n{situation}"

    try:
        result = await llm.complete(
            prompt=user_input,
            system=system,
            max_tokens=300,
        )
        response = result.get("text", "").strip()
    except Exception as e:
        log.warn("jarvis_llm_failed", error=str(e))
        response = "I'm afraid I encountered an error, sir. Please check the server logs."

    log.info("jarvis_response", input_len=len(user_input), response_len=len(response))

    if speak:
        await speak_async(response)

    if broadcast_fn:
        await broadcast_fn({
            "type":     "jarvis_response",
            "input":    user_input,
            "response": response,
        })

    return response


async def proactive_check(broadcast_fn=None) -> Optional[str]:
    """
    Called every 60s by the proactive scheduler.
    Returns a spoken insight if something warrants Jarvis speaking up unprompted.
    """
    from server.llm_router import llm

    situation = await asyncio.to_thread(_build_situation)
    if not situation:
        return None

    prompt = (
        "Review the current situation below. "
        "If something genuinely requires Parv's attention right now — an urgent email, "
        "an overdue task, a project blocker, a new insight worth sharing — state it in "
        "one sentence as Jarvis would say it aloud. "
        "If nothing is urgent, reply with exactly: SILENT\n\n"
        f"{situation}"
    )

    try:
        result = await llm.complete(prompt=prompt, system=_JARVIS_SYSTEM, max_tokens=80)
        text = result.get("text", "").strip()
    except Exception:
        return None

    if text.upper().startswith("SILENT") or not text:
        return None

    log.info("jarvis_proactive", msg=text[:80])
    await speak_async(text)

    if broadcast_fn:
        await broadcast_fn({"type": "jarvis_proactive", "message": text})

    return text


# ── Proactive scheduler ───────────────────────────────────────────────────────

_running = False
_PROACTIVE_INTERVAL = 60   # seconds between checks


async def run_proactive_scheduler(broadcast_fn=None) -> None:
    """Register as a FastAPI lifespan background task."""
    global _running
    _running = True
    log.info("jarvis_scheduler_started")

    while _running:
        try:
            await proactive_check(broadcast_fn)
        except Exception as e:
            log.warn("jarvis_scheduler_error", error=str(e))
        await asyncio.sleep(_PROACTIVE_INTERVAL)


def stop_proactive_scheduler() -> None:
    global _running
    _running = False
