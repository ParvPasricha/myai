"""
Conversation Router — the oversight layer that decides how every input is handled.

Priority order:
  1. Regex fast-path  →  clearly casual/conversational  →  jarvis_core.think()
  2. Short-input rule →  ≤3 words with no action verb   →  jarvis_core.think()
  3. LLM classifier   →  one-word "direct" or "agent"   →  route accordingly
  4. Agents path      →  head_agent.handle()            →  decompose + dispatch

This prevents "wsp gang" or "can you hear me" from triggering subagent dispatch.
"""
import re
from observability.logger import log

_DIRECT_PATTERNS = [
    r"^(hey|hi|hello|wsp|wassup|what'?s up|sup|yo|hiya|heyo)\b",
    r"^can you hear me",
    r"^are you (there|listening|awake|online|working|ok)",
    r"^(good (morning|evening|night|afternoon))\b",
    r"^(how are you|how'?re you doing|how'?s it going)\s*\??$",
    r"^(yes|no|yeah|nah|okay|ok|sure|thanks|thank you|got it|sounds good|cool|nice|perfect|great)\s*[.!]?\s*$",
    r"^(stop|pause|cancel|nevermind|never mind|forget it)\s*$",
    r"^(what('?s)? (going on|up|happening))\s*\??$",
    r"^(what (time|day|date) is it)\s*\??$",
    r"^(who are you|what are you)\s*\??$",
    r"^(test|testing)\s*\d*\s*$",
    r"^(hello\s*)?jarvis\s*\??$",
    r"^(status|how'?s? (everything|the system|things))\s*\??$",
    r"^(wsp|wyd|wbu|sup)\s*(gang|bro|man|dude)?\s*\??$",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _DIRECT_PATTERNS]

_ACTION_VERBS = {
    "search", "find", "research", "look up", "google", "browse",
    "send", "email", "message", "text", "compose", "draft",
    "remind", "schedule", "create", "plan", "review", "check",
    "play", "open", "close", "run", "execute", "deploy",
    "buy", "order", "book", "reserve", "write", "generate",
    "summarise", "summarize", "analyse", "analyze",
}

_CLASSIFY_SYSTEM = """\
You are the routing layer for J.A.R.V.I.S. Classify the input as EXACTLY one of:
  direct — conversational, Jarvis can answer from his own knowledge/memory/context
  agent  — requires external action: web search, email, messaging, code review, music, reminders, browser, file ops

Reply with exactly ONE word: direct OR agent. No explanation.
"""


def _is_direct(text: str) -> bool:
    t = text.strip()
    words = t.split()
    if len(words) <= 3:
        return True
    for pat in _COMPILED:
        if pat.search(t):
            return True
    if len(words) <= 8 and not any(v in t.lower() for v in _ACTION_VERBS):
        return True
    return False


async def _llm_classify(text: str) -> str:
    try:
        from server.llm_router import llm
        result = await llm.complete(
            prompt=f"Input: {text}",
            system=_CLASSIFY_SYSTEM,
            max_tokens=5,
        )
        word = result.get("text", "").strip().lower()
        return "direct" if "direct" in word else "agent"
    except Exception:
        return "direct"   # fail-safe: don't fire agents unnecessarily


async def route_and_respond(
    user_input: str,
    broadcast_fn=None,
    speak: bool = True,
) -> str:
    """
    Overseer entry point for all voice and text input.

    All traffic flows through the brain orchestrator which handles:
      intent classification → memory check → model tier selection →
      confidence gate → hallucination guard → final answer.

    Casual phrases (wsp, can you hear me, etc.) are fast-pathed before
    the orchestrator to skip the overhead.
    """
    text = user_input.strip()
    if not text:
        return ""

    # Fast path: clearly casual — skip orchestrator overhead entirely
    if _is_direct(text):
        log.info("conv_router", path="direct_fast", input=text[:60])
        from intelligence.jarvis_core import think
        return await think(text, speak=speak, broadcast_fn=broadcast_fn)

    # Everything else → brain orchestrator (intent → tier → gate → guard)
    log.info("conv_router", path="orchestrator", input=text[:60])
    from brain.orchestrator import run as orchestrate
    return await orchestrate(text, broadcast_fn=broadcast_fn, speak=speak)
