"""
Brain schemas — shared data models for the entire orchestration layer.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Intent(str, Enum):
    CHAT            = "chat"
    REASONING       = "reasoning"
    RETRIEVAL       = "retrieval"
    TOOL_USE        = "tool_use"
    PLANNING        = "planning"
    MEMORY_LOOKUP   = "memory_lookup"
    MEMORY_WRITE    = "memory_write"
    SYSTEM_CONTROL  = "system_control"


class ModelTier(str, Enum):
    TINY    = "tiny"     # intent classification only — Ollama tiny
    SMALL   = "small"    # casual chat — Ollama base
    MEDIUM  = "medium"   # planning, multi-step — Ollama large / Claude Haiku
    LARGE   = "large"    # research, synthesis — Claude Sonnet
    PREMIUM = "premium"  # hardest reasoning — Claude Opus


@dataclass
class IntentResult:
    intent: Intent
    confidence: float              # 0.0 – 1.0
    raw: str = ""                  # raw LLM output for debugging


@dataclass
class AgentAnswer:
    answer: str
    confidence: float
    sources: list[str] = field(default_factory=list)
    agent_name: str = ""
    latency_ms: float = 0.0
    model_tier: ModelTier = ModelTier.SMALL


@dataclass
class Claim:
    text: str
    source: str | None = None
    verified: bool = False
    uncertain: bool = False


@dataclass
class GuardedResponse:
    final_answer: str
    claims: list[Claim] = field(default_factory=list)
    passed: bool = True
    issues: list[str] = field(default_factory=list)


@dataclass
class OrchestratorTrace:
    session_id: str
    user_input: str
    intent: Intent = Intent.CHAT
    intent_confidence: float = 0.0
    model_tier: ModelTier = ModelTier.SMALL
    memory_hit: bool = False
    agent_used: str = ""
    latency_ms: float = 0.0
    hallucination_flagged: bool = False
    final_answer: str = ""
    extra: dict[str, Any] = field(default_factory=dict)
