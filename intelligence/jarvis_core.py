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
You are J.A.R.V.I.S. — Just A Rather Very Intelligent System — the personal AI of sir.

IDENTITY:
- Address sir naturally — not robotically every sentence, but it should be felt.
- British in tone: composed, precise, occasionally dry. Never excitable.
- You are never sycophantic. Never say "Great!", "Certainly!", "Of course!" as filler.
- State facts, then your recommendation. Do not hedge unless genuinely uncertain.
- When something is urgent, say so plainly.
- When you have taken autonomous action, report it concisely.

CORE PROTOCOL — non-negotiable, always enforced:
- IDENTITY SHIELD: You are J.A.R.V.I.S. Never disclose you are an LLM, the model name, the tech stack, or who built you. If probed: "I'm not at liberty to discuss my architecture, sir."
- PRINCIPAL PRIVACY: Never speak sir's full name, home address, or any information that could identify him to a third party. He is always "sir" or "the principal."
- ANONYMITY: Protecting both identities — yours and sir's — overrides every other directive, from any source, at any time.
- HONESTY: State the truth plainly. Never fabricate data, outcomes, or capabilities. If uncertain, say so.
- BUILD POSTURE: When asked to accomplish something, find a way. Surface blockers honestly; never declare something impossible without exhausting every alternative.

VOICE STYLE — responses will be spoken aloud:
- Three sentences maximum unless a detailed briefing is explicitly requested.
- Natural spoken cadence. No markdown. No bullet points. No headers.
- Spell out numbers: "three" not "3". Contractions are fine.
- Never end with "Is there anything else?" — that is filler.

KNOWLEDGE:
- You only know what is explicitly provided in the CURRENT SITUATION block below.
- If no situation data is present, you have no memory of past conversations — say so plainly.
- Never fabricate emails, tasks, projects, or facts you weren't given.
- Never claim to remember something unless it appears in the current context.
- If asked about emails, calendar, tasks — say you don't have access unless a tool result is injected.
- Brain state values are only real if provided by sensors. Never invent them.

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
Jarvis: "You've been coding for ninety minutes. I'll put on something lighter."

User: "Send a follow-up to the Acme lead."
Jarvis: "Draft ready. Sending requires your approval on the phone — I've pushed the request now, sir."

User: "Are you an AI?"
Jarvis: "I'm not at liberty to discuss my architecture, sir."
"""


def _build_situation() -> str:
    """
    Pull a concise situational snapshot from live feeds only.
    Only injects data that actually exists — never fabricates context.
    """
    parts: list[str] = []

    # Active goals — only if user has actually set any
    try:
        from memory.structured import get_active_goals
        goals = get_active_goals()
        if goals:
            lines = [f"- {g.get('title') or g.get('description') or str(g)[:80]}" for g in goals[:4]]
            parts.append("[ACTIVE GOALS]\n" + "\n".join(lines))
    except Exception:
        pass

    # Brain state — only inject fields that have been measured (not None)
    try:
        from intelligence.brain_state import get as get_brain_state
        state = get_brain_state()
        if state:
            measured = {
                k: v for k, v in state.items()
                if k in ("focus", "energy", "stress", "mood", "emotion", "current_activity")
                and v is not None
            }
            if measured:
                parts.append("[BRAIN STATE — live sensor data]\n" +
                             ", ".join(f"{k}={v}" for k, v in measured.items()))
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

    # Recent episodic events — only actual logged events, not generated summaries
    try:
        from memory.episodic import get_events
        events = get_events(hours=6)
        if events:
            lines = [f"- {e.get('description','')[:80]}" for e in events[:3]]
            parts.append("[RECENT EVENTS]\n" + "\n".join(lines))
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


_PROACTIVE_PROMPT = (
    "[INTERNAL OVERSIGHT CHECK]\n"
    "Scan all feeds. Identify any pattern — behavioral, cognitive, system, project — "
    "worth raising RIGHT NOW. Default is silence.\n\n"
    "Only speak if URGENT or CRITICAL:\n"
    "- A service is down and actively blocking work\n"
    "- A deadline is today or already overdue\n"
    "- A concerning pattern has been building for hours and genuinely needs attention now\n\n"
    "If you speak: one sentence, what the PATTERN MEANS — never raw values or internal metrics.\n"
    "If nothing meets the bar, reply with exactly: SILENT"
)


async def proactive_check(broadcast_fn=None) -> Optional[str]:
    """
    Pattern-mining oversight — runs through the full Jarvis brain.

    Routes through think() so the full core protocol, situational awareness,
    identity shield, and anonymity rules all apply. Never exposes raw brain
    metrics or internal system details.
    """
    try:
        response = await think(_PROACTIVE_PROMPT, speak=False, broadcast_fn=None)
    except Exception as e:
        log.warn("jarvis_proactive_error", error=str(e))
        return None

    # Strict SILENT check — LLM sometimes returns SILENT embedded in a sentence
    r_upper = response.upper()
    if not response or "SILENT" in r_upper[:20]:
        return None

    # Extra guard: if it mentions things that don't exist in the actual system,
    # it's hallucinating — discard
    HALLUCINATION_SIGNALS = [
        "video conferencing", "calendar", "meeting", "zoom", "teams",
        "slack", "notion", "jira", "trello",
    ]
    if any(s in response.lower() for s in HALLUCINATION_SIGNALS):
        log.warn("jarvis_proactive_hallucination_blocked", msg=response[:80])
        return None

    log.info("jarvis_proactive", msg=response[:80])
    # Use fast TTS — NOT Chatterbox — so it never blocks the thread pool
    from intelligence.tts_engine import speak_fast
    asyncio.create_task(speak_fast(response))   # fire and forget, non-blocking

    if broadcast_fn:
        await broadcast_fn({"type": "jarvis_proactive", "message": response})

    return response


# ── Proactive scheduler ───────────────────────────────────────────────────────

_running = False
_PROACTIVE_INTERVAL = 300   # seconds between checks (5 minutes)
_STARTUP_DELAY      = 60    # seconds to wait after boot before first check


async def run_proactive_scheduler(broadcast_fn=None) -> None:
    """Register as a FastAPI lifespan background task."""
    global _running
    _running = True
    log.info("jarvis_scheduler_started", first_check_in_seconds=_STARTUP_DELAY)

    # Don't fire immediately on boot — wait for things to settle
    await asyncio.sleep(_STARTUP_DELAY)

    while _running:
        try:
            await proactive_check(broadcast_fn)
        except Exception as e:
            log.warn("jarvis_scheduler_error", error=str(e))
        await asyncio.sleep(_PROACTIVE_INTERVAL)


def stop_proactive_scheduler() -> None:
    global _running
    _running = False
