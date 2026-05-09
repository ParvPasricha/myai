"""
Working memory — Layer 1 of the 4-layer memory system.

Stores the active conversation context (last N exchanges) in Redis with a 24h TTL.
Falls back to an in-process dict when Redis is unavailable so the server never crashes.

Key structure:
    parv:session:<session_id>:messages   → JSON list of {role, content, ts}
    parv:session:<session_id>:meta       → JSON {started_at, topic, activity}
    parv:working:last_session_id         → str (most recent session)
"""
import json
import time
import uuid
from typing import Any

import redis as redis_lib

from server.config import REDIS_URL

_TTL = 86400          # 24 hours
_MAX_MESSAGES = 20    # keep last 20 turns per session
_PREFIX = "parv:session"

# In-process fallback
_local: dict[str, list] = {}
_r: redis_lib.Redis | None = None


def _redis() -> redis_lib.Redis | None:
    global _r
    if _r is not None:
        return _r
    try:
        r = redis_lib.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        _r = r
        return _r
    except Exception:
        return None


# ── Session management ────────────────────────────────────────────────────────

def new_session(topic: str | None = None, activity: str | None = None) -> str:
    sid = str(uuid.uuid4())[:8]
    meta = {"started_at": time.time(), "topic": topic, "activity": activity}
    r = _redis()
    if r:
        r.setex(f"{_PREFIX}:{sid}:meta", _TTL, json.dumps(meta))
        r.setex(f"{_PREFIX}:{sid}:messages", _TTL, json.dumps([]))
        r.setex("parv:working:last_session_id", _TTL, sid)
    else:
        _local[sid] = []
    return sid


def get_last_session_id() -> str | None:
    r = _redis()
    if r:
        return r.get("parv:working:last_session_id")
    return next(iter(_local), None)


# ── Messages ──────────────────────────────────────────────────────────────────

def append_message(session_id: str, role: str, content: str) -> None:
    msg = {"role": role, "content": content, "ts": time.time()}
    r = _redis()
    if r:
        key = f"{_PREFIX}:{session_id}:messages"
        raw = r.get(key)
        messages = json.loads(raw) if raw else []
        messages.append(msg)
        messages = messages[-_MAX_MESSAGES:]
        r.setex(key, _TTL, json.dumps(messages))
    else:
        _local.setdefault(session_id, []).append(msg)
        _local[session_id] = _local[session_id][-_MAX_MESSAGES:]


def get_messages(session_id: str) -> list[dict]:
    r = _redis()
    if r:
        raw = r.get(f"{_PREFIX}:{session_id}:messages")
        return json.loads(raw) if raw else []
    return _local.get(session_id, [])


def get_context_block(session_id: str, max_chars: int = 2000) -> str:
    """Return the last N messages formatted as a context string."""
    msgs = get_messages(session_id)
    lines = [f"{m['role'].upper()}: {m['content']}" for m in msgs]
    block = "\n".join(lines)
    return block[-max_chars:] if len(block) > max_chars else block


def clear_session(session_id: str) -> None:
    r = _redis()
    if r:
        r.delete(f"{_PREFIX}:{session_id}:messages")
        r.delete(f"{_PREFIX}:{session_id}:meta")
    _local.pop(session_id, None)


# ── Convenience: get or create current session ────────────────────────────────

def current_session() -> str:
    sid = get_last_session_id()
    if not sid:
        sid = new_session()
    return sid
