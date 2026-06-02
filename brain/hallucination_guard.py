"""
Hallucination Guard — every factual response passes through this firewall.

Pipeline:
  LLM Response
       ↓
  Claim Extractor     — pulls out factual assertions
       ↓
  Evidence Checker    — checks each claim against memory/retrieval
       ↓
  Critic Agent        — flags unsupported claims
       ↓
  Final Answer        — uncertain claims marked, fabrications removed

Rule: every factual claim must have a source or be marked uncertain.
"""
from __future__ import annotations
import re
from brain.schemas import Claim, GuardedResponse
from observability.logger import log

_EXTRACT_SYSTEM = """\
Extract all factual claims from the text below.
Return JSON array only: [{"text": "...", "needs_source": true/false}, ...]
A claim needs_source if it asserts a specific fact (date, number, name, event).
Opinions and hedged statements do not need sources.
"""

_CRITIC_SYSTEM = """\
You are a critic. Given a claim and available evidence, decide:
- verified: claim is supported by evidence
- uncertain: claim may be true but no evidence provided
- fabricated: claim contradicts evidence or is clearly invented

Reply with JSON: {"verdict": "verified|uncertain|fabricated", "reason": "..."}
"""

# Patterns that indicate hallucination risk
_HIGH_RISK = re.compile(
    r"\b(according to|studies show|research confirms|it is known that|"
    r"statistics show|experts say|scientists found|the latest|as of \d{4})\b",
    re.I,
)


def _is_factual_response(text: str) -> bool:
    """Quick check — does this response contain factual assertions worth guarding?"""
    if len(text.split()) < 15:
        return False
    if _HIGH_RISK.search(text):
        return True
    # Count sentences with specific nouns/numbers
    sentences = [s.strip() for s in re.split(r"[.!?]", text) if s.strip()]
    factual = sum(1 for s in sentences if re.search(r"\b\d+|[A-Z][a-z]+\s[A-Z][a-z]+\b", s))
    return factual >= 2


async def _extract_claims(text: str) -> list[dict]:
    try:
        import json as _json
        from server.llm_router import llm
        raw = await llm.complete(
            prompt=f"Text:\n{text}",
            system=_EXTRACT_SYSTEM,
            max_tokens=300,
        )
        start = raw["text"].find("[")
        end   = raw["text"].rfind("]") + 1
        return _json.loads(raw["text"][start:end]) if start >= 0 else []
    except Exception as e:
        log.warn("claim_extract_failed", error=str(e))
        return []


async def _check_claim(claim_text: str) -> tuple[str, str]:
    """Returns (verdict, reason). verdict: verified | uncertain | fabricated"""
    # Check memory first
    evidence = ""
    try:
        from intelligence.unified_memory import get_relevant_context
        evidence = get_relevant_context(claim_text, n_each=1)
    except Exception:
        pass

    if not evidence:
        return "uncertain", "no supporting evidence in memory"

    try:
        import json as _json
        from server.llm_router import llm
        raw = await llm.complete(
            prompt=f"Claim: {claim_text}\n\nEvidence:\n{evidence}",
            system=_CRITIC_SYSTEM,
            max_tokens=80,
        )
        data = _json.loads(raw["text"].strip())
        return data.get("verdict", "uncertain"), data.get("reason", "")
    except Exception:
        return "uncertain", "critic check failed"


async def guard(text: str, always_check: bool = False) -> GuardedResponse:
    """
    Run the hallucination firewall on a response.

    For conversational/short responses: passes through without full pipeline.
    For factual responses: extracts claims, checks evidence, marks uncertain ones.
    """
    if not always_check and not _is_factual_response(text):
        return GuardedResponse(final_answer=text, passed=True)

    log.info("hallucination_guard_running", text_len=len(text))
    raw_claims = await _extract_claims(text)

    claims: list[Claim] = []
    issues: list[str]   = []
    final_parts: list[str] = [text]  # start with full text, patch uncertain claims

    for rc in raw_claims:
        if not rc.get("needs_source", False):
            claims.append(Claim(text=rc["text"], verified=True))
            continue

        verdict, reason = await _check_claim(rc["text"])
        claim = Claim(text=rc["text"])

        if verdict == "verified":
            claim.verified = True
        elif verdict == "fabricated":
            claim.uncertain = True
            issues.append(f"Fabricated claim removed: '{rc['text'][:60]}'")
            log.warn("hallucination_detected", claim=rc["text"][:80], reason=reason)
            # Remove the fabricated sentence from the response
            for sent in re.split(r"(?<=[.!?])\s+", text):
                if rc["text"][:30] in sent:
                    final_parts[0] = final_parts[0].replace(sent, "")
        else:
            claim.uncertain = True
            # Hedge the claim inline
            final_parts[0] = final_parts[0].replace(
                rc["text"],
                f"{rc['text']} (unverified)",
            )

        claims.append(claim)

    final_answer = final_parts[0].strip()
    passed = len(issues) == 0

    if not passed:
        from brain import state as brain_state
        brain_state.get().hallucination_count += 1

    return GuardedResponse(
        final_answer=final_answer,
        claims=claims,
        passed=passed,
        issues=issues,
    )
