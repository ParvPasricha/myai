"""
Metrics API — Phase 10.

Proxies Prometheus into clean JSON for the custom monitoring dashboard.
No auth required (all local, same as Prometheus itself).

GET /metrics/dashboard          — all current values in one shot
GET /metrics/history?metric=&m= — time-series for a named metric (last N minutes)
"""
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Query

router = APIRouter()

_PROM = "http://localhost:9090/api/v1"


# ── Prometheus helpers ────────────────────────────────────────────────────────

async def _instant(query: str) -> float:
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{_PROM}/query", params={"query": query})
            results = r.json().get("data", {}).get("result", [])
            return float(results[0]["value"][1]) if results else 0.0
    except Exception:
        return 0.0


async def _instant_many(query: str) -> list[dict]:
    """Returns all label sets for a vector query."""
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{_PROM}/query", params={"query": query})
            return r.json().get("data", {}).get("result", [])
    except Exception:
        return []


async def _range(query: str, minutes: int = 180, step: int = 60) -> list[dict]:
    """Returns [{ts, value}] for a scalar metric over the last N minutes."""
    end = int(time.time())
    start = end - minutes * 60
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{_PROM}/query_range",
                            params={"query": query, "start": start,
                                    "end": end, "step": str(step)})
            results = r.json().get("data", {}).get("result", [])
            if not results:
                return []
            return [{"ts": float(ts), "value": float(v)}
                    for ts, v in results[0]["values"]]
    except Exception:
        return []


async def _range_labeled(query: str, minutes: int = 60,
                          step: int = 30) -> list[dict]:
    """Returns [{labels, values: [{ts, value}]}] for a labeled metric."""
    end = int(time.time())
    start = end - minutes * 60
    try:
        async with httpx.AsyncClient(timeout=5.0) as c:
            r = await c.get(f"{_PROM}/query_range",
                            params={"query": query, "start": start,
                                    "end": end, "step": str(step)})
            results = r.json().get("data", {}).get("result", [])
            return [
                {
                    "labels": s.get("metric", {}),
                    "values": [{"ts": float(ts), "value": float(v)}
                               for ts, v in s.get("values", [])],
                }
                for s in results
            ]
    except Exception:
        return []


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/metrics/dashboard")
async def metrics_dashboard():
    """
    All monitoring data in one call. The frontend polls this every 15 s.
    """
    import asyncio

    # Parallel fetches
    (
        focus, energy, stress,
        llm_ok_24h, llm_err_1h,
        latency_p95,
        redis, ollama, mqtt,
        deadman,
        alerts_raw,
    ) = await asyncio.gather(
        _instant("parv_brain_state_focus"),
        _instant("parv_brain_state_energy"),
        _instant("parv_brain_state_stress"),
        _instant("increase(parv_llm_requests_total{status='ok'}[24h])"),
        _instant("increase(parv_llm_requests_total{status='error'}[1h])"),
        _instant("histogram_quantile(0.95, rate(parv_llm_latency_seconds_bucket[10m]))"),
        _instant("parv_redis_up"),
        _instant("parv_ollama_up"),
        _instant("parv_mqtt_connected"),
        _instant("parv_deadman_seconds_remaining"),
        _instant_many("parv_alerts_total"),
    )

    # Top HTTP endpoints (by request count in last hour)
    http_raw = await _instant_many(
        "topk(8, increase(parv_http_requests_total[1h]))"
    )
    http_endpoints = [
        {
            "method": r["metric"].get("method", "?"),
            "path":   r["metric"].get("path", "?"),
            "status": r["metric"].get("status", "?"),
            "count":  round(float(r["value"][1]), 1),
        }
        for r in http_raw
        if float(r["value"][1]) > 0
    ]
    http_endpoints.sort(key=lambda x: x["count"], reverse=True)

    alerts = [
        {"name": r["metric"].get("alert_name", "?"),
         "total": round(float(r["value"][1]))}
        for r in alerts_raw
    ]

    return {
        "ts": time.time(),
        "brain_state": {
            "focus":  round(focus, 1),
            "energy": round(energy, 1),
            "stress": round(stress, 1),
        },
        "llm": {
            "requests_24h": round(llm_ok_24h),
            "errors_1h":    round(llm_err_1h),
            "latency_p95":  round(latency_p95, 2),
        },
        "infra": {
            "redis":    redis >= 0.5,
            "ollama":   ollama >= 0.5,
            "mqtt":     mqtt >= 0.5,
            "deadman_s": round(deadman),
        },
        "http_endpoints": http_endpoints[:8],
        "alerts": alerts,
    }


@router.get("/metrics/history")
async def metrics_history(
    metric: str = Query(...),
    minutes: int = Query(180, ge=10, le=1440),
    step: int = Query(60, ge=15, le=300),
):
    """
    Time-series for a named shorthand:
      focus | energy | stress | llm_latency | llm_requests | deadman
    """
    query_map = {
        "focus":        "parv_brain_state_focus",
        "energy":       "parv_brain_state_energy",
        "stress":       "parv_brain_state_stress",
        "llm_latency":  "histogram_quantile(0.95, rate(parv_llm_latency_seconds_bucket[5m]))",
        "llm_requests": "rate(parv_llm_requests_total{status='ok'}[5m])",
        "deadman":      "parv_deadman_seconds_remaining",
    }
    query = query_map.get(metric, metric)
    data = await _range(query, minutes=minutes, step=step)
    return {"metric": metric, "minutes": minutes, "points": data}


@router.get("/metrics/http_history")
async def http_history(minutes: int = Query(60, ge=5, le=360)):
    """Request rate per endpoint over time."""
    data = await _range_labeled(
        "topk(5, rate(parv_http_requests_total[2m]))",
        minutes=minutes, step=30,
    )
    return {"minutes": minutes, "series": data}
