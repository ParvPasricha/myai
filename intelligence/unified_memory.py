"""
Unified Memory Layer — Phase 10.

Single persistent store that grows forever across all domains.
Backs the learning engine, decision logger, and visual layer.

Collections (prefixed intel_ to avoid collision with Phase 5 memory):
  intel_conversations   — every conversation summarised + domain-tagged
  intel_habits          — recurring behavioural patterns detected
  intel_domain_knowledge — domain-specific facts the AI learned
  intel_work_patterns   — how Parv approaches work in each domain

Decisions stored in SQLite for structured querying.
"""
import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

import chromadb
from sentence_transformers import SentenceTransformer

_DB_PATH = Path(__file__).parent.parent / "memory" / "intelligence.db"
_CHROMA_PATH = Path(__file__).parent.parent / "memory" / "chromadb"
_CHROMA_PATH.mkdir(parents=True, exist_ok=True)

_MODEL_NAME = "all-MiniLM-L6-v2"
_COLLECTIONS = (
    "intel_conversations",
    "intel_habits",
    "intel_domain_knowledge",
    "intel_work_patterns",
    "intel_dreams",          # approved dream patterns only
)

_chroma: Optional[chromadb.ClientAPI] = None
_model: Optional[SentenceTransformer] = None
_sqlite: Optional[sqlite3.Connection] = None


def _get_chroma() -> chromadb.ClientAPI:
    global _chroma
    if _chroma is None:
        _chroma = chromadb.PersistentClient(path=str(_CHROMA_PATH))
    return _chroma


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(_MODEL_NAME)
    return _model


def _get_sqlite() -> sqlite3.Connection:
    global _sqlite
    if _sqlite is None:
        _sqlite = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        _sqlite.row_factory = sqlite3.Row
        _sqlite.executescript("""
            CREATE TABLE IF NOT EXISTS decisions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                ts         REAL    NOT NULL,
                actor      TEXT    NOT NULL,
                content    TEXT    NOT NULL,
                reasoning  TEXT    DEFAULT '',
                domain     TEXT    DEFAULT 'general',
                decision_type TEXT DEFAULT 'action',
                outcome    TEXT    DEFAULT '',
                tags       TEXT    DEFAULT '[]'
            );
            CREATE INDEX IF NOT EXISTS idx_dec_ts     ON decisions(ts);
            CREATE INDEX IF NOT EXISTS idx_dec_domain ON decisions(domain);
            CREATE INDEX IF NOT EXISTS idx_dec_actor  ON decisions(actor);

            -- Dream sessions: each nightly run is one session
            CREATE TABLE IF NOT EXISTS dream_sessions (
                id           TEXT    PRIMARY KEY,    -- uuid hex
                started_at   REAL    NOT NULL,
                finished_at  REAL,
                tasks_total  INTEGER DEFAULT 0,
                tasks_approved INTEGER DEFAULT 0,
                status       TEXT    DEFAULT 'running'   -- running|done|failed
            );

            -- Individual dream tasks within a session
            CREATE TABLE IF NOT EXISTS dreams (
                id              TEXT    PRIMARY KEY,
                session_id      TEXT    NOT NULL REFERENCES dream_sessions(id),
                ts              REAL    NOT NULL,
                strategy        TEXT    NOT NULL,  -- remix|blend|edge_case|contradiction
                prompt          TEXT    NOT NULL,
                response        TEXT    NOT NULL,
                score_consistency REAL,
                score_novelty     REAL,
                score_usefulness  REAL,
                score_safety      REAL,
                score_composite   REAL,
                approved        INTEGER DEFAULT 0,
                rejection_reason TEXT    DEFAULT '',
                source_ids      TEXT    DEFAULT '[]'   -- JSON list of memory IDs used
            );
            CREATE INDEX IF NOT EXISTS idx_dreams_session ON dreams(session_id);
            CREATE INDEX IF NOT EXISTS idx_dreams_approved ON dreams(approved, score_composite);

            -- GDLE sessions: each targeted learning run
            CREATE TABLE IF NOT EXISTS gdle_sessions (
                id           TEXT    PRIMARY KEY,
                topic        TEXT    NOT NULL,
                depth        TEXT    NOT NULL DEFAULT 'intermediate',
                style        TEXT    DEFAULT '',
                constraints  TEXT    DEFAULT '',
                started_at   REAL    NOT NULL,
                finished_at  REAL,
                status       TEXT    DEFAULT 'running',
                avg_score    REAL,
                guide        TEXT    DEFAULT ''
            );

            -- GDLE concepts: per-subtopic derivations within a session
            CREATE TABLE IF NOT EXISTS gdle_concepts (
                id           TEXT    PRIMARY KEY,
                session_id   TEXT    NOT NULL REFERENCES gdle_sessions(id),
                subtopic     TEXT    NOT NULL,
                derivation   TEXT    DEFAULT '',
                problems     TEXT    DEFAULT '[]',
                critique     TEXT    DEFAULT '{}',
                score        REAL    DEFAULT 0,
                ts           REAL    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_gdle_concepts_session ON gdle_concepts(session_id);

            -- Raw observations: terminal commands, screen states, topic research
            CREATE TABLE IF NOT EXISTS observations (
                id       TEXT    PRIMARY KEY,
                ts       REAL    NOT NULL,
                type     TEXT    NOT NULL,   -- terminal|screen|topic
                content  TEXT    NOT NULL,
                domain   TEXT    DEFAULT 'general',
                metadata TEXT    DEFAULT '{}'
            );
            CREATE INDEX IF NOT EXISTS idx_obs_type ON observations(type, ts);

            -- Discovered connections between memory items
            CREATE TABLE IF NOT EXISTS connections (
                id       TEXT    PRIMARY KEY,
                ts       REAL    NOT NULL,
                from_id  TEXT    NOT NULL,
                to_id    TEXT    NOT NULL,
                relation TEXT    NOT NULL,
                strength REAL    DEFAULT 0.5
            );
            CREATE INDEX IF NOT EXISTS idx_conn_from ON connections(from_id);
        """)
        _sqlite.commit()
    return _sqlite


def _embed(text: str) -> list[float]:
    return _get_model().encode(text).tolist()


def _col(name: str):
    return _get_chroma().get_or_create_collection(name)


# ── Store ─────────────────────────────────────────────────────────────────────

def store_conversation(session_id: str, summary: str, domain: str,
                       metadata: Optional[dict] = None) -> str:
    doc_id = f"conv_{session_id}_{int(time.time())}"
    meta = {"session_id": session_id, "domain": domain, "ts": time.time(),
            **(metadata or {})}
    _col("intel_conversations").add(
        ids=[doc_id],
        embeddings=[_embed(summary)],
        documents=[summary],
        metadatas=[meta],
    )
    return doc_id


def store_habit(pattern: str, domain: str, confidence: float = 0.8,
                metadata: Optional[dict] = None) -> str:
    doc_id = f"habit_{domain}_{int(time.time())}"
    meta = {"domain": domain, "confidence": confidence, "ts": time.time(),
            **(metadata or {})}
    _col("intel_habits").add(
        ids=[doc_id],
        embeddings=[_embed(pattern)],
        documents=[pattern],
        metadatas=[meta],
    )
    return doc_id


def store_domain_knowledge(knowledge: str, domain: str,
                            metadata: Optional[dict] = None) -> str:
    doc_id = f"dk_{domain}_{int(time.time())}"
    meta = {"domain": domain, "ts": time.time(), **(metadata or {})}
    _col("intel_domain_knowledge").add(
        ids=[doc_id],
        embeddings=[_embed(knowledge)],
        documents=[knowledge],
        metadatas=[meta],
    )
    return doc_id


def store_work_pattern(pattern: str, domain: str, example: str = "",
                        metadata: Optional[dict] = None) -> str:
    doc_id = f"wp_{domain}_{int(time.time())}"
    text = f"{pattern}: {example}" if example else pattern
    meta = {"domain": domain, "example": example, "ts": time.time(),
            **(metadata or {})}
    _col("intel_work_patterns").add(
        ids=[doc_id],
        embeddings=[_embed(text)],
        documents=[pattern],
        metadatas=[meta],
    )
    return doc_id


def log_decision(actor: str, content: str, reasoning: str = "",
                  domain: str = "general", decision_type: str = "action",
                  tags: Optional[list[str]] = None) -> int:
    db = _get_sqlite()
    cursor = db.execute(
        """INSERT INTO decisions
           (ts, actor, content, reasoning, domain, decision_type, tags)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (time.time(), actor, content, reasoning, domain, decision_type,
         json.dumps(tags or [])),
    )
    db.commit()
    return cursor.lastrowid  # type: ignore[return-value]


def update_decision_outcome(decision_id: int, outcome: str) -> None:
    db = _get_sqlite()
    db.execute("UPDATE decisions SET outcome = ? WHERE id = ?",
               (outcome, decision_id))
    db.commit()


# ── Search ────────────────────────────────────────────────────────────────────

def search_memory(query: str, n_each: int = 3) -> dict[str, list[dict]]:
    results: dict[str, list[dict]] = {}
    emb = _embed(query)
    for col_name in _COLLECTIONS:
        try:
            col = _col(col_name)
            if col.count() == 0:
                continue
            r = col.query(query_embeddings=[emb],
                          n_results=min(n_each, col.count()))
            results[col_name] = _fmt(r)
        except Exception:
            pass
    return results


def search_decisions(domain: Optional[str] = None, actor: Optional[str] = None,
                     since: Optional[float] = None, n: int = 20) -> list[dict]:
    db = _get_sqlite()
    where: list[str] = []
    params: list[Any] = []
    if domain:
        where.append("domain = ?")
        params.append(domain)
    if actor:
        where.append("actor = ?")
        params.append(actor)
    if since:
        where.append("ts >= ?")
        params.append(since)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    rows = db.execute(
        f"SELECT * FROM decisions {clause} ORDER BY ts DESC LIMIT ?",
        params + [n],
    ).fetchall()
    return [dict(r) for r in rows]


def get_relevant_context(query: str, n_each: int = 2) -> str:
    """Returns a text block of relevant memories for LLM context injection."""
    all_results = search_memory(query, n_each=n_each)
    parts: list[str] = []
    for col_name, items in all_results.items():
        label = col_name.replace("intel_", "").replace("_", " ").title()
        for item in items:
            parts.append(f"[{label}] {item['text']}")
    return "\n".join(parts[:10])


def memory_stats() -> dict:
    client = _get_chroma()
    stats: dict[str, int] = {}
    for name in _COLLECTIONS:
        try:
            stats[name] = client.get_or_create_collection(name).count()
        except Exception:
            stats[name] = 0
    db = _get_sqlite()
    stats["decisions"] = db.execute(
        "SELECT COUNT(*) FROM decisions"
    ).fetchone()[0]
    return stats


def recent_conversations(n: int = 10) -> list[dict]:
    try:
        col = _col("intel_conversations")
        if col.count() == 0:
            return []
        results = col.get(limit=n, include=["documents", "metadatas"])
        docs = results.get("documents") or []
        metas = results.get("metadatas") or []
        ids = results.get("ids") or []
        out = []
        for d, m, i in zip(docs, metas, ids):
            out.append({"id": i, "text": d, "metadata": m})
        out.sort(key=lambda x: x["metadata"].get("ts", 0), reverse=True)
        return out[:n]
    except Exception:
        return []


# ── Dream store ───────────────────────────────────────────────────────────────

def create_dream_session(session_id: str) -> None:
    db = _get_sqlite()
    db.execute(
        "INSERT OR IGNORE INTO dream_sessions (id, started_at) VALUES (?, ?)",
        (session_id, time.time()),
    )
    db.commit()


def store_dream(
    session_id: str,
    dream_id: str,
    strategy: str,
    prompt: str,
    response: str,
    scores: dict,
    approved: bool,
    rejection_reason: str = "",
    source_ids: Optional[list[str]] = None,
) -> None:
    composite = scores.get("composite", 0.0)
    db = _get_sqlite()
    db.execute(
        """INSERT INTO dreams
           (id, session_id, ts, strategy, prompt, response,
            score_consistency, score_novelty, score_usefulness, score_safety,
            score_composite, approved, rejection_reason, source_ids)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            dream_id, session_id, time.time(), strategy, prompt, response,
            scores.get("consistency"), scores.get("novelty"),
            scores.get("usefulness"), scores.get("safety"),
            composite, int(approved), rejection_reason,
            json.dumps(source_ids or []),
        ),
    )
    # Update session counters
    db.execute(
        "UPDATE dream_sessions SET tasks_total = tasks_total + 1 WHERE id = ?",
        (session_id,),
    )
    if approved:
        db.execute(
            "UPDATE dream_sessions SET tasks_approved = tasks_approved + 1 WHERE id = ?",
            (session_id,),
        )
        # Store in ChromaDB so it's semantically searchable
        _col("intel_dreams").add(
            ids=[dream_id],
            embeddings=[_embed(response)],
            documents=[response[:1000]],
            metadatas=[{
                "session_id": session_id,
                "strategy": strategy,
                "score": composite,
                "ts": time.time(),
            }],
        )
    db.commit()


def finish_dream_session(session_id: str, status: str = "done") -> None:
    db = _get_sqlite()
    db.execute(
        "UPDATE dream_sessions SET finished_at=?, status=? WHERE id=?",
        (time.time(), status, session_id),
    )
    db.commit()


def get_dream_sessions(n: int = 10) -> list[dict]:
    db = _get_sqlite()
    rows = db.execute(
        "SELECT * FROM dream_sessions ORDER BY started_at DESC LIMIT ?", (n,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_dream_session(session_id: str) -> Optional[dict]:
    db = _get_sqlite()
    row = db.execute(
        "SELECT * FROM dream_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if not row:
        return None
    session = dict(row)
    tasks = db.execute(
        "SELECT * FROM dreams WHERE session_id=? ORDER BY ts", (session_id,)
    ).fetchall()
    session["tasks"] = [dict(t) for t in tasks]
    return session


def get_approved_dreams(n: int = 20, min_score: float = 0.65) -> list[dict]:
    db = _get_sqlite()
    rows = db.execute(
        """SELECT * FROM dreams WHERE approved=1 AND score_composite>=?
           ORDER BY score_composite DESC LIMIT ?""",
        (min_score, n),
    ).fetchall()
    return [dict(r) for r in rows]


def delete_dream(dream_id: str) -> bool:
    db = _get_sqlite()
    count = db.execute("DELETE FROM dreams WHERE id=?", (dream_id,)).rowcount
    db.commit()
    # Remove from ChromaDB too
    try:
        _col("intel_dreams").delete(ids=[dream_id])
    except Exception:
        pass
    return count > 0


def dream_sessions_today() -> int:
    since = time.time() - 86400
    db = _get_sqlite()
    return db.execute(
        "SELECT COUNT(*) FROM dream_sessions WHERE started_at>?", (since,)
    ).fetchone()[0]


# ── GDLE store ───────────────────────────────────────────────────────────────

def create_gdle_session(session_id: str, topic: str, depth: str = "intermediate",
                         style: str = "", constraints: str = "") -> None:
    db = _get_sqlite()
    db.execute(
        """INSERT OR IGNORE INTO gdle_sessions
           (id, topic, depth, style, constraints, started_at)
           VALUES (?,?,?,?,?,?)""",
        (session_id, topic, depth, style, constraints, time.time()),
    )
    db.commit()


def store_gdle_concept(concept: dict) -> None:
    db = _get_sqlite()
    db.execute(
        """INSERT OR REPLACE INTO gdle_concepts
           (id, session_id, subtopic, derivation, problems, critique, score, ts)
           VALUES (?,?,?,?,?,?,?,?)""",
        (
            concept["id"],
            concept["session_id"],
            concept["subtopic"],
            concept.get("derivation", ""),
            json.dumps(concept.get("problems", [])),
            json.dumps(concept.get("critique", {})),
            concept.get("score", 0.0),
            concept.get("ts", time.time()),
        ),
    )
    db.commit()


def finish_gdle_session(session_id: str, status: str, avg_score: float = 0.0,
                         guide: str = "") -> None:
    db = _get_sqlite()
    db.execute(
        "UPDATE gdle_sessions SET finished_at=?, status=?, avg_score=?, guide=? WHERE id=?",
        (time.time(), status, avg_score, guide, session_id),
    )
    db.commit()


def get_gdle_sessions(n: int = 10) -> list[dict]:
    db = _get_sqlite()
    rows = db.execute(
        "SELECT * FROM gdle_sessions ORDER BY started_at DESC LIMIT ?", (n,)
    ).fetchall()
    return [dict(r) for r in rows]


def get_gdle_session(session_id: str) -> Optional[dict]:
    db = _get_sqlite()
    row = db.execute(
        "SELECT * FROM gdle_sessions WHERE id=?", (session_id,)
    ).fetchone()
    if not row:
        return None
    session = dict(row)
    concepts = db.execute(
        "SELECT * FROM gdle_concepts WHERE session_id=? ORDER BY ts", (session_id,)
    ).fetchall()
    parsed = []
    for c in concepts:
        d = dict(c)
        d["problems"] = json.loads(d.get("problems", "[]") or "[]")
        d["critique"] = json.loads(d.get("critique", "{}") or "{}")
        parsed.append(d)
    session["concepts"] = parsed
    return session


# ── Observations + connections ────────────────────────────────────────────────

def store_observation(obs_id: str, obs_type: str, content: str,
                      domain: str = "general", metadata: Optional[dict] = None) -> None:
    db = _get_sqlite()
    db.execute(
        "INSERT OR IGNORE INTO observations (id, ts, type, content, domain, metadata) VALUES (?,?,?,?,?,?)",
        (obs_id, time.time(), obs_type, content, domain, json.dumps(metadata or {})),
    )
    db.commit()


def store_connection(from_id: str, to_id: str, relation: str, strength: float = 0.5) -> None:
    import uuid
    conn_id = f"conn_{uuid.uuid4().hex[:8]}"
    db = _get_sqlite()
    db.execute(
        "INSERT OR IGNORE INTO connections (id, ts, from_id, to_id, relation, strength) VALUES (?,?,?,?,?,?)",
        (conn_id, time.time(), from_id, to_id, relation, strength),
    )
    db.commit()


def get_recent_observations(obs_type: Optional[str] = None, n: int = 20) -> list[dict]:
    db = _get_sqlite()
    if obs_type:
        rows = db.execute(
            "SELECT * FROM observations WHERE type=? ORDER BY ts DESC LIMIT ?",
            (obs_type, n),
        ).fetchall()
    else:
        rows = db.execute(
            "SELECT * FROM observations ORDER BY ts DESC LIMIT ?", (n,)
        ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        out.append(d)
    return out


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fmt(results: dict) -> list[dict]:
    out = []
    docs = results.get("documents", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    dists = results.get("distances", [[]])[0]
    ids = results.get("ids", [[]])[0]
    for doc, meta, dist, doc_id in zip(docs, metas, dists, ids):
        out.append({"id": doc_id, "text": doc, "metadata": meta,
                    "distance": dist})
    return out
