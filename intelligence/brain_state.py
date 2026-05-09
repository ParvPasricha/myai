"""
Brain State — single source of truth for PARV-AI.

Every subsystem reads from and writes to this.
Backed by Redis (live, sub-ms) with an in-process dict fallback when Redis
is unavailable. Historical snapshots are written to PostgreSQL in Phase 5.
"""
import json
import time
from typing import Any, Optional
import redis

from server.config import REDIS_URL

_REDIS_KEY = "parv:brain_state"

_DEFAULT: dict = {
    "focus": 5,
    "energy": 5,
    "stress": 3,
    "deep_work": False,
    "social_mode": False,
    "learning_mode": None,
    "security_state": "armed",
    "current_activity": "idle",
    "location": "unknown",
    "mic_stage": "push_to_talk",
    "brainwave": None,          # populated in Phase 12
    "last_updated": None,
}

# In-process fallback when Redis is not running
_local: dict = dict(_DEFAULT)
_redis: Optional[redis.Redis] = None


def _get_redis() -> Optional[redis.Redis]:
    global _redis
    if _redis is not None:
        return _redis
    try:
        r = redis.from_url(REDIS_URL, decode_responses=True, socket_connect_timeout=1)
        r.ping()
        _redis = r
        return _redis
    except Exception:
        return None


def get() -> dict:
    r = _get_redis()
    if r:
        try:
            raw = r.get(_REDIS_KEY)
            if raw:
                return json.loads(raw)
        except Exception:
            pass
    return dict(_local)


def update(patch: dict) -> dict:
    state = get()
    state.update(patch)
    state["last_updated"] = time.time()

    r = _get_redis()
    if r:
        try:
            r.set(_REDIS_KEY, json.dumps(state))
        except Exception:
            pass

    _local.update(state)
    return state


def get_field(key: str, default: Any = None) -> Any:
    return get().get(key, default)


def set_field(key: str, value: Any) -> dict:
    return update({key: value})


def reset() -> dict:
    return update(dict(_DEFAULT))
