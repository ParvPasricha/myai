"""
Topic Researcher — autonomous multi-step web research for a given topic.

Flow:
  1. Generate 4 search angles from the topic
  2. DuckDuckGo search each angle, scrape top 2 results per angle
  3. LLM synthesizes each page into a structured knowledge chunk
  4. Store each chunk in intel_domain_knowledge
  5. Find connections between new chunks and existing memory
  6. Return research summary

No Redis dependency — uses existing web_search + unified_memory infrastructure.
"""
import asyncio
import time
import uuid
from typing import Optional

from intelligence import unified_memory
from intelligence.domain_detector import detect as detect_domain
from observability.logger import log

_SYNTH_SYSTEM = (
    "Extract factual knowledge from web content. Be precise. "
    "No filler, no summaries of summaries. Output the actual facts."
)


async def _search_angles(llm, topic: str, depth: str) -> list[str]:
    """Generate 4 distinct search queries covering the topic from different angles."""
    prompt = (
        f"Topic: {topic}\nDepth: {depth}\n\n"
        f"Generate 4 distinct Google-style search queries that together give "
        f"comprehensive coverage of this topic. Different angles — not paraphrases. "
        f'Return ONLY a JSON array of strings: ["query1", "query2", "query3", "query4"]'
    )
    result = await llm.complete(
        prompt=prompt,
        system="Return ONLY valid JSON arrays of strings. No other text.",
        max_tokens=200,
    )
    text = result.get("text", "")
    try:
        import json
        start = text.find("[")
        end   = text.rfind("]") + 1
        queries = json.loads(text[start:end])
        return [q for q in queries if isinstance(q, str)][:4]
    except Exception:
        return [topic, f"{topic} explained", f"{topic} examples", f"{topic} advanced"]


async def _ddg(query: str, n: int = 3) -> list[dict]:
    try:
        from duckduckgo_search import DDGS
        return await asyncio.to_thread(
            lambda: list(DDGS().text(query, max_results=n))
        )
    except Exception:
        return []


async def _scrape(url: str) -> str:
    try:
        import trafilatura
        html = await asyncio.to_thread(trafilatura.fetch_url, url)
        return trafilatura.extract(html) or ""
    except Exception:
        return ""


async def _synthesize(llm, topic: str, query: str, content: str) -> str:
    """Turn raw web content into a clean knowledge chunk."""
    prompt = (
        f"Topic context: {topic}\nSearch angle: {query}\n\n"
        f"Web content:\n{content[:2000]}\n\n"
        f"Extract the key factual knowledge from this content relevant to the topic. "
        f"Be concrete and specific. 3–5 sentences max. No fluff."
    )
    result = await llm.complete(
        prompt=prompt, system=_SYNTH_SYSTEM, max_tokens=300
    )
    return result.get("text", "").strip()


async def research_topic(
    topic: str,
    depth: str = "intermediate",
    broadcast_fn=None,
) -> dict:
    """
    Full autonomous research session for a topic.
    Returns: {topic, queries, chunks_stored, connections_found, session_id}
    """
    from server.llm_router import llm

    session_id = uuid.uuid4().hex[:8]
    domain     = detect_domain(topic)
    chunks_stored = 0
    connections_found = 0

    if broadcast_fn:
        await broadcast_fn({"type": "research_start", "topic": topic, "session_id": session_id})

    log.info("topic_research_start", topic=topic, depth=depth)

    # Step 1: Generate search angles
    queries = await _search_angles(llm, topic, depth)
    if broadcast_fn:
        await broadcast_fn({"type": "research_queries", "queries": queries})

    # Step 2–4: Search → scrape → synthesize per angle (max 2 concurrent)
    sem = asyncio.Semaphore(2)

    async def _process_query(query: str) -> int:
        nonlocal chunks_stored, connections_found
        stored = 0
        async with sem:
            results = await _ddg(query, n=2)
        for r in results[:2]:
            url  = r.get("href", "")
            body = r.get("body", "")

            # Try to scrape full text; fall back to snippet
            async with sem:
                full = await _scrape(url)
            content = full[:2000] if full else body[:500]
            if not content:
                continue

            async with sem:
                chunk = await _synthesize(llm, topic, query, content)
            if not chunk:
                continue

            # Store in domain knowledge
            doc_id = f"research_{session_id}_{uuid.uuid4().hex[:6]}"
            await asyncio.to_thread(
                unified_memory.store_domain_knowledge,
                chunk, domain,
                {"source": "topic_research", "url": url,
                 "query": query, "session_id": session_id},
            )
            chunks_stored += 1

            # Find connections to existing memory
            related = await asyncio.to_thread(
                unified_memory.search_memory, chunk[:200], 2
            )
            for col_items in related.values():
                for item in col_items:
                    if item.get("distance", 1.0) < 0.45:
                        await asyncio.to_thread(
                            unified_memory.store_connection,
                            doc_id, item["id"],
                            f"research_supports:{domain}",
                            round(1.0 - item.get("distance", 0.5), 2),
                        )
                        connections_found += 1

            if broadcast_fn:
                await broadcast_fn({
                    "type":    "research_chunk",
                    "query":   query,
                    "url":     url,
                    "preview": chunk[:150],
                })

        return stored

    await asyncio.gather(*[_process_query(q) for q in queries])

    # Store observation record
    obs_id = f"topic_{session_id}"
    await asyncio.to_thread(
        unified_memory.store_observation,
        obs_id, "topic",
        f"Researched: {topic}",
        domain,
        {"depth": depth, "queries": queries, "chunks": chunks_stored},
    )

    summary = {
        "session_id":       session_id,
        "topic":            topic,
        "domain":           domain,
        "queries":          queries,
        "chunks_stored":    chunks_stored,
        "connections_found": connections_found,
    }

    if broadcast_fn:
        await broadcast_fn({"type": "research_done", **summary})

    log.info("topic_research_done", **{k: v for k, v in summary.items() if k != "queries"})
    return summary
