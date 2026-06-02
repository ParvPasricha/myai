"""
Brain state — live runtime state for the orchestrator.

Tracks: current session, active intent, pending tasks, model tier in use.
Stored in-process (not persisted). Reset on server restart.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any
from brain.schemas import Intent, ModelTier


@dataclass
class BrainState:
    session_id: str           = ""
    current_intent: Intent    = Intent.CHAT
    current_tier: ModelTier   = ModelTier.SMALL
    last_input: str           = ""
    last_response: str        = ""
    last_ts: float            = 0.0
    pending_tasks: list[str]  = field(default_factory=list)
    memory_hit: bool          = False
    request_count: int        = 0
    hallucination_count: int  = 0
    routing_log: list[dict]   = field(default_factory=list)

    def record_request(
        self,
        intent: Intent,
        tier: ModelTier,
        latency_ms: float,
        memory_hit: bool = False,
        hallucination: bool = False,
    ) -> None:
        self.request_count += 1
        self.current_intent = intent
        self.current_tier   = tier
        self.memory_hit     = memory_hit
        self.last_ts        = time.time()
        if hallucination:
            self.hallucination_count += 1

        entry = {
            "ts":        self.last_ts,
            "intent":    intent.value,
            "tier":      tier.value,
            "latency_ms": round(latency_ms, 1),
            "memory_hit": memory_hit,
        }
        self.routing_log.append(entry)
        if len(self.routing_log) > 200:
            self.routing_log = self.routing_log[-200:]

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id":          self.session_id,
            "current_intent":      self.current_intent.value,
            "current_tier":        self.current_tier.value,
            "request_count":       self.request_count,
            "hallucination_count": self.hallucination_count,
            "memory_hit":          self.memory_hit,
            "pending_tasks":       len(self.pending_tasks),
            "last_ts":             self.last_ts,
        }


# ── Global singleton ──────────────────────────────────────────────────────────
_state = BrainState()


def get() -> BrainState:
    return _state


def snapshot() -> dict[str, Any]:
    return _state.snapshot()
