"""
Router — classifies intent and selects model tier + execution path.

Intent → path:
  chat           → small model, direct Jarvis response
  reasoning      → medium model, chain-of-thought
  retrieval      → tools first, skip LLM if memory hit
  tool_use       → tool agent
  planning       → planner agent + medium/large model
  memory_lookup  → memory agent, skip LLM if found
  memory_write   → memory agent write, confirm to user
  system_control → system_control path
"""
from __future__ import annotations
import re
import time
from brain.schemas import Intent, IntentResult, ModelTier
from observability.logger import log

# ── Fast-path patterns (no LLM call needed) ───────────────────────────────────

_INTENT_PATTERNS: list[tuple[re.Pattern, Intent]] = [
    # memory_write
    (re.compile(r"\b(remember|save|note|store|record)\b.{0,60}", re.I), Intent.MEMORY_WRITE),
    # memory_lookup
    (re.compile(r"\b(do you remember|recall|what did i|when did i|have i)\b", re.I), Intent.MEMORY_LOOKUP),
    # system_control
    (re.compile(r"\b(restart|shutdown|kill|stop server|reload)\b", re.I), Intent.SYSTEM_CONTROL),
    # tool_use
    (re.compile(r"\b(send|email|message|open|launch|run|execute|play music)\b", re.I), Intent.TOOL_USE),
    # planning
    (re.compile(r"\b(plan|roadmap|milestones|steps to|how (should|do) i build)\b", re.I), Intent.PLANNING),
    # retrieval
    (re.compile(r"\b(search|find|look up|what is|who is|when did|latest|current)\b", re.I), Intent.RETRIEVAL),
    # reasoning
    (re.compile(r"\b(why|explain|analyse|analyze|compare|difference between|pros and cons)\b", re.I), Intent.REASONING),
]

# Greetings / casual → chat
_CHAT_PATTERNS = re.compile(
    r"^(hey|hi|hello|wsp|wassup|sup|yo|how are you|what'?s up|good (morning|evening|night)"
    r"|thanks|thank you|ok|okay|yes|no|cool|got it|sounds good)\b",
    re.I,
)

_CLASSIFY_SYSTEM = """\
Classify the user input into EXACTLY one intent class.
Classes: chat, reasoning, retrieval, tool_use, planning, memory_lookup, memory_write, system_control

Reply with JSON only: {"intent": "<class>", "confidence": <0.0-1.0>}
No explanation. No markdown.
"""


def _pattern_classify(text: str) -> IntentResult | None:
    """Fast pattern match — returns result or None if ambiguous."""
    t = text.strip()
    words = t.split()

    if len(words) <= 4 or _CHAT_PATTERNS.match(t):
        return IntentResult(intent=Intent.CHAT, confidence=0.97, raw="pattern:chat")

    for pat, intent in _INTENT_PATTERNS:
        if pat.search(t):
            return IntentResult(intent=intent, confidence=0.88, raw=f"pattern:{intent.value}")

    return None


async def classify_intent(text: str) -> IntentResult:
    """Classify intent — fast pattern first, LLM fallback."""
    result = _pattern_classify(text)
    if result:
        log.info("intent_classified", method="pattern",
                 intent=result.intent, confidence=result.confidence)
        return result

    # LLM fallback
    try:
        import json as _json
        from server.llm_router import llm
        raw = await llm.complete(
            prompt=f"Input: {text}",
            system=_CLASSIFY_SYSTEM,
            max_tokens=40,
        )
        data = _json.loads(raw["text"].strip())
        intent  = Intent(data.get("intent", "chat"))
        conf    = float(data.get("confidence", 0.75))
        result  = IntentResult(intent=intent, confidence=conf, raw=raw["text"])
        log.info("intent_classified", method="llm",
                 intent=intent, confidence=round(conf, 3))
        return result
    except Exception as e:
        log.warn("intent_classify_failed", error=str(e))
        return IntentResult(intent=Intent.CHAT, confidence=0.5, raw="fallback")


def select_tier(intent: Intent, confidence: float) -> ModelTier:
    """
    Select model tier based on intent + confidence.

    Low confidence → escalate one tier for safer answers.
    """
    base: dict[Intent, ModelTier] = {
        Intent.CHAT:           ModelTier.SMALL,
        Intent.REASONING:      ModelTier.MEDIUM,
        Intent.RETRIEVAL:      ModelTier.SMALL,    # tools do the work
        Intent.TOOL_USE:       ModelTier.SMALL,
        Intent.PLANNING:       ModelTier.MEDIUM,
        Intent.MEMORY_LOOKUP:  ModelTier.TINY,
        Intent.MEMORY_WRITE:   ModelTier.TINY,
        Intent.SYSTEM_CONTROL: ModelTier.SMALL,
    }
    tier = base.get(intent, ModelTier.SMALL)

    # Escalate if confidence is low
    if confidence < 0.65:
        from brain.confidence import escalate_tier
        tier = escalate_tier(tier)

    return tier
