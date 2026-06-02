"""
Confidence Gate — every agent answer passes through here.

Thresholds:
  < 0.60  → verify   (try a second source / escalate model tier)
  0.60–0.85 → cross-check (critic agent reviews)
  > 0.85  → answer   (pass through directly)
"""
from __future__ import annotations
from brain.schemas import AgentAnswer, ModelTier
from observability.logger import log

LOW_THRESHOLD  = 0.60
HIGH_THRESHOLD = 0.85


def gate(answer: AgentAnswer) -> str:
    """
    Returns one of: 'answer' | 'cross_check' | 'verify'
    """
    c = answer.confidence
    if c > HIGH_THRESHOLD:
        decision = "answer"
    elif c >= LOW_THRESHOLD:
        decision = "cross_check"
    else:
        decision = "verify"

    log.info("confidence_gate",
             agent=answer.agent_name,
             confidence=round(c, 3),
             decision=decision)
    return decision


def escalate_tier(current: ModelTier) -> ModelTier:
    """Return the next model tier up for verification passes."""
    order = [ModelTier.TINY, ModelTier.SMALL, ModelTier.MEDIUM,
             ModelTier.LARGE, ModelTier.PREMIUM]
    try:
        idx = order.index(current)
        return order[min(idx + 1, len(order) - 1)]
    except ValueError:
        return ModelTier.LARGE
