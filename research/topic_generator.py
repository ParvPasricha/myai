"""
Generates today's research topic using the LLM.

Selection logic (in priority order):
  1. Weak areas from past quiz scores (score < 60) — revisit and improve
  2. Domains not covered in the last 14 days — ensure breadth
  3. Random pick from active domains — general exploration

The LLM then produces a specific, focused topic + a 3-sentence research brief.
"""
import json
import time
from datetime import date

from research.db import (
    get_today_topic, save_topic, get_recent_topics,
    get_weak_areas, get_active_domains,
)
from server.llm_router import llm
from observability.logger import log


_SYSTEM = """You are the research curator for PARV-AI, a personal AI system.
Your job is to assign one focused daily research topic that is intellectually stimulating and genuinely useful.
Always respond with valid JSON only — no markdown, no explanation outside the JSON."""


async def generate_today_topic(force: bool = False) -> dict:
    """
    Generate and persist today's topic.
    If today's topic already exists and force=False, return existing.
    """
    today = date.today().isoformat()

    existing = get_today_topic(today)
    if existing and not force:
        log.info("topic_already_exists", date=today, topic=existing["topic"])
        return existing

    # Build context for the LLM
    domains = get_active_domains()
    recent = get_recent_topics(14)
    recent_topics = [r["topic"] for r in recent]
    weak_areas = get_weak_areas(5)

    context = {
        "available_domains": domains,
        "recent_topics_to_avoid": recent_topics,
        "weak_areas_to_revisit": [
            {"topic": w["topic"], "avg_score": round(w["avg_score"] or 0, 1)}
            for w in weak_areas
        ],
    }

    prompt = f"""
Given this context about the learner's history:
{json.dumps(context, indent=2)}

Select ONE research topic for today ({today}).

Rules:
- If there are weak areas with score < 60, prefer revisiting one of those
- Otherwise pick from available_domains, avoiding recent_topics
- Make it specific (not just "Machine Learning" — say "Attention Mechanisms in Transformers")
- The topic should take 2-4 hours of focused research to cover meaningfully

Respond with JSON:
{{
  "topic": "exact topic name",
  "description": "3-sentence brief explaining what to research and why it matters",
  "domains": ["primary domain", "optional secondary domain"]
}}
"""

    result = await llm.complete(prompt=prompt, system=_SYSTEM, max_tokens=300)
    text = result["text"].strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    text = text.strip()

    data = json.loads(text)
    topic_id = save_topic(
        date=today,
        topic=data["topic"],
        description=data["description"],
        domains=data.get("domains", []),
        ts=time.time(),
    )

    result_dict = get_today_topic(today)
    log.info("topic_generated", date=today, topic=data["topic"], tier=result["tier"])
    # Fallback: if DB read returns None (race/edge case), construct from data dict
    return result_dict or {
        "id": topic_id, "date": today,
        "topic": data["topic"], "description": data["description"],
        "domains": json.dumps(data.get("domains", [])), "generated_at": time.time(),
    }
