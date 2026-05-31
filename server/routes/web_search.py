"""
Live web search + scrape routes.

GET  /web/search?q=...&n=5     — DuckDuckGo search, returns top N results
POST /web/scrape                — scrape a URL, return clean extracted text
POST /web/ask                   — search + scrape + answer via LLM (one-shot)
"""
import asyncio
from typing import Optional

import httpx
import trafilatura
from duckduckgo_search import DDGS
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from server.auth import require_auth
from observability.logger import log

router = APIRouter()


# ── Search ────────────────────────────────────────────────────────────────────

def _ddg_search(query: str, n: int = 5) -> list[dict]:
    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=n):
            results.append({
                "title": r.get("title", ""),
                "url":   r.get("href", ""),
                "body":  r.get("body", ""),
            })
    return results


@router.get("/web/search")
async def web_search(
    q: str = Query(..., min_length=1),
    n: int = Query(5, ge=1, le=10),
    _auth: dict = Depends(require_auth),
):
    try:
        results = await asyncio.to_thread(_ddg_search, q, n)
        log.info("web_search", query=q, results=len(results))
        return {"query": q, "results": results}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search failed: {e}")


# ── Scrape ────────────────────────────────────────────────────────────────────

def _scrape(url: str) -> str:
    try:
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return ""
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            no_fallback=False,
        )
        return text or ""
    except Exception:
        return ""


class ScrapeBody(BaseModel):
    url: str
    max_chars: int = 4000


@router.post("/web/scrape")
async def web_scrape(body: ScrapeBody, _auth: dict = Depends(require_auth)):
    text = await asyncio.to_thread(_scrape, body.url)
    if not text:
        raise HTTPException(status_code=422, detail="Could not extract content from URL.")
    log.info("web_scrape", url=body.url, chars=len(text))
    return {"url": body.url, "text": text[:body.max_chars], "chars": len(text)}


# ── Search + Answer ───────────────────────────────────────────────────────────

class AskBody(BaseModel):
    question: str
    n_results: int = 4
    scrape_top: int = 2      # how many top URLs to deep-scrape for full text


@router.post("/web/ask")
async def web_ask(body: AskBody, _auth: dict = Depends(require_auth)):
    """
    Search the web for the question, scrape top results, feed to LLM, return answer.
    This is what the AI uses internally for live-info queries.
    """
    from server.llm_router import llm

    # 1. Search
    try:
        results = await asyncio.to_thread(_ddg_search, body.question, body.n_results)
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Search failed: {e}")

    if not results:
        raise HTTPException(status_code=404, detail="No results found.")

    # 2. Scrape top N for full article text
    async def maybe_scrape(r: dict) -> str:
        text = await asyncio.to_thread(_scrape, r["url"])
        if text:
            return f"[{r['title']}]({r['url']})\n{text[:1500]}"
        return f"[{r['title']}]({r['url']})\n{r['body']}"

    scraped = await asyncio.gather(*[
        maybe_scrape(r) for r in results[:body.scrape_top]
    ])
    snippets = [r["body"] for r in results[body.scrape_top:]]

    # 3. Build context
    sources_block = "\n\n---\n\n".join(list(scraped) + snippets)

    system = (
        "You have live web search results. Answer the question using only what's in the sources. "
        "Be direct and specific. Cite sources inline like [Source Title]. "
        "If the sources don't answer the question, say so."
    )
    prompt = (
        f"Question: {body.question}\n\n"
        f"Sources:\n{sources_block[:6000]}"
    )

    result = await llm.complete(prompt=prompt, system=system, max_tokens=800)

    log.info("web_ask", question=body.question, sources=len(results))
    return {
        "question": body.question,
        "answer":   result["text"],
        "sources":  [{"title": r["title"], "url": r["url"]} for r in results],
        "model":    result.get("model"),
    }
