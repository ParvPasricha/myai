"""
Semantic memory — Layer 3.

Stores vector embeddings of conversation summaries, distilled facts,
and intent lessons in ChromaDB (embedded, no separate server).

Model: all-MiniLM-L6-v2 (384-dim, 90MB, fast on CPU)

Collections:
    parv_summaries    — nightly conversation summaries
    parv_facts        — extracted facts ("user prefers X", "item at Y")
    parv_lessons      — intent correction lessons ("when user says X they mean Y")
"""
import time
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer

_CHROMA_PATH = Path(__file__).parent.parent / "memory" / "chromadb"
_CHROMA_PATH.mkdir(parents=True, exist_ok=True)

_MODEL_NAME = "all-MiniLM-L6-v2"

# Lazy singletons
_client: chromadb.ClientAPI | None = None
_model: SentenceTransformer | None = None


def _get_client() -> chromadb.ClientAPI:
    global _client
    if _client is None:
        _client = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    return _client


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _embed(text: str) -> list[float]:
    return _get_model().encode(text).tolist()


def _collection(name: str):
    return _get_client().get_or_create_collection(name)


# ── Summaries ─────────────────────────────────────────────────────────────────

def add_summary(session_id: str, summary_text: str, metadata: dict | None = None) -> str:
    doc_id = f"summary_{session_id}_{int(time.time())}"
    meta = {"session_id": session_id, "ts": time.time(), **(metadata or {})}
    _collection("parv_summaries").add(
        ids=[doc_id],
        embeddings=[_embed(summary_text)],
        documents=[summary_text],
        metadatas=[meta],
    )
    return doc_id


def search_summaries(query: str, n: int = 3) -> list[dict]:
    results = _collection("parv_summaries").query(
        query_embeddings=[_embed(query)], n_results=n
    )
    return _format_results(results)


# ── Facts ─────────────────────────────────────────────────────────────────────

def add_fact(fact_text: str, category: str, metadata: dict | None = None) -> str:
    doc_id = f"fact_{category}_{int(time.time())}"
    meta = {"category": category, "ts": time.time(), **(metadata or {})}
    _collection("parv_facts").add(
        ids=[doc_id],
        embeddings=[_embed(fact_text)],
        documents=[fact_text],
        metadatas=[meta],
    )
    return doc_id


def search_facts(query: str, n: int = 5) -> list[dict]:
    results = _collection("parv_facts").query(
        query_embeddings=[_embed(query)], n_results=n
    )
    return _format_results(results)


# ── Intent lessons ────────────────────────────────────────────────────────────

def add_lesson(lesson_text: str, context: str, metadata: dict | None = None) -> str:
    doc_id = f"lesson_{int(time.time())}"
    meta = {"context": context, "ts": time.time(), **(metadata or {})}
    _collection("parv_lessons").add(
        ids=[doc_id],
        embeddings=[_embed(lesson_text)],
        documents=[lesson_text],
        metadatas=[meta],
    )
    return doc_id


def search_lessons(query: str, n: int = 3) -> list[dict]:
    results = _collection("parv_lessons").query(
        query_embeddings=[_embed(query)], n_results=n
    )
    return _format_results(results)


# ── General semantic search across all collections ────────────────────────────

def search_all(query: str, n_each: int = 2) -> list[dict]:
    results = []
    for col_name in ("parv_summaries", "parv_facts", "parv_lessons"):
        try:
            col = _collection(col_name)
            if col.count() == 0:
                continue
            r = col.query(query_embeddings=[_embed(query)],
                          n_results=min(n_each, col.count()))
            for item in _format_results(r):
                item["collection"] = col_name
                results.append(item)
        except Exception:
            pass
    results.sort(key=lambda x: x.get("distance", 1))
    return results


def stats() -> dict:
    client = _get_client()
    out = {}
    for name in ("parv_summaries", "parv_facts", "parv_lessons"):
        try:
            out[name] = client.get_or_create_collection(name).count()
        except Exception:
            out[name] = 0
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_results(results: dict) -> list[dict]:
    out = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]
    for doc, meta, dist, doc_id in zip(docs, metas, dists, ids):
        out.append({"id": doc_id, "text": doc, "metadata": meta, "distance": dist})
    return out
