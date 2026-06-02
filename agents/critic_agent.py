"""
Critic Agent — reviews answers for issues before they reach the user.

Input:  original question + proposed answer
Output: list of issues (empty = no issues found)

Cannot: answer the user, access external tools.
Can:    identify logical errors, missing caveats, unsupported claims,
        inconsistencies with known facts.
"""
from __future__ import annotations
from observability.logger import log

_CRITIC_SYSTEM = """\
You are a critic reviewing an AI answer for quality issues.

Check for:
1. Factual claims without evidence
2. Logical inconsistencies
3. Missing important caveats
4. Overconfident assertions on uncertain topics
5. Answers that don't address what was actually asked

Return a JSON array of issue strings. Empty array [] if no issues found.
Be strict but fair. Only flag genuine problems.
Example: ["Claims X without evidence", "Doesn't address the core question"]
"""


async def critique(question: str, answer: str) -> list[str]:
    """
    Review the answer and return a list of issue strings.
    Returns [] if the answer passes review.
    """
    try:
        import json as _json
        from server.llm_router import llm

        prompt = f"Question: {question}\n\nProposed answer: {answer}"
        result = await llm.complete(
            prompt=prompt,
            system=_CRITIC_SYSTEM,
            max_tokens=200,
        )
        raw  = result.get("text", "[]").strip()
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        issues: list[str] = _json.loads(raw[start:end]) if start >= 0 else []
        log.info("critic_done", issues_found=len(issues))
        return issues
    except Exception as e:
        log.warn("critic_failed", error=str(e))
        return []
