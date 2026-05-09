"""
Nightly distillation — runs at 02:00 daily.

Steps:
  1. Pull last 24h of conversations from episodic SQLite
  2. LLM summarises each session into a paragraph
  3. LLM extracts structured facts (decisions, goals, habits, item mentions)
  4. Embed summaries → ChromaDB parv_summaries
  5. Write extracted facts → structured SQLite tables
  6. Snapshot Brain State → structured DB
  7. Clear Redis working memory
"""
import asyncio
import json
from datetime import datetime, timedelta

from observability.logger import log
from memory import episodic, semantic, structured, working
from intelligence import brain_state as bs


_DISTILL_SYSTEM = """You are a memory consolidation AI. Extract structured information from conversations.
Respond with valid JSON only."""


async def _summarise_session(messages: list[dict], llm) -> str:
    if not messages:
        return ""
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages[-20:]
    )
    prompt = f"""Summarise this conversation in 2-3 sentences, focusing on:
- What the user asked or discussed
- Decisions made or preferences expressed
- Any important facts mentioned

Conversation:
{transcript[:3000]}

Respond with JSON: {{"summary": "..."}}"""

    result = await llm.complete(prompt=prompt, system=_DISTILL_SYSTEM, max_tokens=200)
    text = result["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(text).get("summary", "")
    except json.JSONDecodeError:
        log.warn("distill_summarise_json_error", raw=text[:200])
        return ""


async def _extract_facts(messages: list[dict], llm) -> dict:
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in messages[-20:]
    )
    prompt = f"""Extract structured facts from this conversation.

Conversation:
{transcript[:3000]}

Respond with JSON:
{{
  "decisions": ["..."],
  "goals": [{{"description": "...", "domain": "..."}}],
  "habits": [{{"type": "...", "description": "..."}}],
  "item_locations": [{{"object": "...", "zone": "..."}}],
  "preferences": ["..."]
}}

Use empty lists if nothing found. Be conservative — only include clearly stated facts."""

    result = await llm.complete(prompt=prompt, system=_DISTILL_SYSTEM, max_tokens=400)
    text = result["text"].strip()
    if text.startswith("```"):
        text = text.split("```")[1].lstrip("json").strip()
    try:
        return json.loads(text)
    except Exception:
        return {}


async def run_distillation():
    from server.llm_router import llm

    log.info("distillation_start")
    start = datetime.now()

    # 1. Get last 24h conversations
    messages = episodic.get_recent(hours=24, limit=500)
    if not messages:
        log.info("distillation_skip", reason="no messages in last 24h")
        return

    # Group by session
    sessions: dict[str, list] = {}
    for m in messages:
        sessions.setdefault(m["session_id"], []).append(m)

    summaries_count = 0
    facts_count = 0
    successfully_processed: set[str] = set()   # only clear sessions that succeeded

    for session_id, session_msgs in sessions.items():
        if not session_msgs:
            continue

        session_ok = True

        # 2. Summarise
        try:
            summary = await _summarise_session(session_msgs, llm)
            if summary:
                semantic.add_summary(
                    session_id=session_id,
                    summary_text=summary,
                    metadata={"date": start.date().isoformat(), "msg_count": len(session_msgs)},
                )
                episodic.set_summary(session_id, summary)
                summaries_count += 1
        except Exception as e:
            session_ok = False
            log.error("distillation_summarise_error", session=session_id, error=str(e))

        # 3. Extract facts
        try:
            facts = await _extract_facts(session_msgs, llm)
            for decision in facts.get("decisions", []):
                if decision:
                    structured.log_decision(decision)
                    semantic.add_fact(f"Decision: {decision}", category="decision")
                    facts_count += 1
            for goal in facts.get("goals", []):
                if goal.get("description"):
                    structured.add_goal(goal["description"], domain=goal.get("domain"))
                    facts_count += 1
            for habit in facts.get("habits", []):
                if habit.get("type"):
                    structured.log_habit(habit["type"], habit.get("description"))
                    facts_count += 1
            for item in facts.get("item_locations", []):
                if item.get("object") and item.get("zone"):
                    structured.upsert_item_sighting(item["object"], item["zone"])
                    facts_count += 1
            for pref in facts.get("preferences", []):
                if pref:
                    semantic.add_fact(f"Preference: {pref}", category="preference")
                    facts_count += 1
        except Exception as e:
            session_ok = False
            log.error("distillation_extract_error", session=session_id, error=str(e))

        if session_ok:
            successfully_processed.add(session_id)

    # 4. Snapshot Brain State
    try:
        structured.snapshot_brain_state(bs.get())
    except Exception as e:
        log.error("distillation_snapshot_error", error=str(e))

    # 5. Only clear sessions that were fully processed — failed ones retry next run
    for session_id in successfully_processed:
        working.clear_session(session_id)
    skipped = len(sessions) - len(successfully_processed)
    if skipped:
        log.warn("distillation_sessions_skipped", count=skipped, reason="processing errors")

    elapsed = (datetime.now() - start).total_seconds()
    log.info("distillation_complete",
             sessions=len(sessions),
             summaries=summaries_count,
             facts=facts_count,
             elapsed_s=round(elapsed, 1))


async def run_distillation_scheduler():
    log.info("distillation_scheduler_started")
    while True:
        now = datetime.now()
        # Fire at 02:00 daily
        target = now.replace(hour=2, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        log.info("distillation_next", wait_hours=round(wait / 3600, 1))
        await asyncio.sleep(wait)
        await run_distillation()
        await asyncio.sleep(60)   # prevent re-firing within same minute
