"""
Aggregate health checker — used by GET /health.

Each checker is async and returns {"status": "ok"|"degraded"|"down", ...}.
"""
import asyncio
import time
from typing import Any

import httpx
import redis as redis_lib

from server.config import REDIS_URL, OLLAMA_BASE_URL
from observability.metrics import redis_up, ollama_up


async def _check_redis() -> dict[str, Any]:
    t0 = time.time()
    try:
        r = redis_lib.from_url(REDIS_URL, socket_connect_timeout=1, decode_responses=True)
        r.ping()
        latency_ms = round((time.time() - t0) * 1000)
        redis_up.set(1)
        return {"status": "ok", "latency_ms": latency_ms}
    except Exception as e:
        redis_up.set(0)
        return {"status": "down", "error": str(e)}


async def _check_ollama() -> dict[str, Any]:
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_BASE_URL}/api/tags")
            latency_ms = round((time.time() - t0) * 1000)
            if r.status_code == 200:
                models = [m["name"] for m in r.json().get("models", [])]
                ollama_up.set(1)
                return {"status": "ok", "latency_ms": latency_ms, "models": models}
            ollama_up.set(0)
            return {"status": "degraded", "http_status": r.status_code}
    except Exception as e:
        ollama_up.set(0)
        return {"status": "down", "error": str(e)}


async def _check_mqtt(mqtt_connected: bool) -> dict[str, Any]:
    return {"status": "ok" if mqtt_connected else "down"}


async def _check_brain_state() -> dict[str, Any]:
    try:
        from intelligence.brain_state import get
        state = get()
        return {"status": "ok", "focus": state.get("focus"), "activity": state.get("current_activity")}
    except Exception as e:
        return {"status": "down", "error": str(e)}


def _check_postgres() -> dict[str, Any]:
    t0 = time.time()
    try:
        from db.postgres import ping
        from memory.structured import using_postgres
        if not using_postgres():
            return {"status": "not_configured"}
        ok = ping()
        latency_ms = round((time.time() - t0) * 1000)
        return {"status": "ok", "latency_ms": latency_ms} if ok else {"status": "down"}
    except Exception as e:
        return {"status": "down", "error": str(e)}


async def full_health(mqtt_connected: bool = False) -> dict[str, Any]:
    redis_result, ollama_result, mqtt_result, brain_result, pg_result = await asyncio.gather(
        _check_redis(),
        _check_ollama(),
        _check_mqtt(mqtt_connected),
        _check_brain_state(),
        asyncio.to_thread(_check_postgres),
    )

    subsystems = {
        "redis":      redis_result,
        "ollama":     ollama_result,
        "mqtt":       mqtt_result,
        "brain_state": brain_result,
        "postgres":   pg_result,
    }

    overall = "ok"
    for name, result in subsystems.items():
        if result["status"] == "down" and name not in ("ollama",):
            overall = "degraded"
            break

    return {"status": overall, "subsystems": subsystems, "ts": time.time()}
