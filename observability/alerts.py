"""
Alert evaluator — runs as a background asyncio task every 30s.

Each rule checks a condition and fires once per state-change (no spam).
APNS push is wired in Phase 3 when the iPhone app exists;
for now alerts are logged + printed.
"""
import asyncio
import time
from typing import Callable, Awaitable

from observability.logger import log
from observability.metrics import alert_fires

# Alert name → last fired timestamp (used to suppress repeats within cooldown)
_last_fired: dict[str, float] = {}
_COOLDOWN_SECONDS = 300   # 5 min between repeat alerts for same rule


def _fire(name: str, message: str, severity: str = "warn"):
    now = time.time()
    if now - _last_fired.get(name, 0) < _COOLDOWN_SECONDS:
        return
    _last_fired[name] = now
    alert_fires.labels(alert_name=name).inc()
    log.warn("alert_fired", alert=name, message=message, severity=severity)
    print(f"\n⚠  ALERT [{severity.upper()}] {name}: {message}\n")
    # TODO Phase 3: push to iPhone via APNS


def _clear(name: str):
    if name in _last_fired:
        del _last_fired[name]


# ── Individual alert rules ───────────────────────────────────────────────────

async def _alert_redis():
    try:
        import redis
        from server.config import REDIS_URL
        r = redis.from_url(REDIS_URL, socket_connect_timeout=1)
        r.ping()
        _clear("redis_down")
    except Exception:
        _fire("redis_down", "Redis is unreachable", severity="critical")


async def _alert_ollama():
    import httpx
    from server.config import OLLAMA_BASE_URL
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            if r.status_code == 200:
                _clear("ollama_down")
                return
    except Exception:
        pass
    _fire("ollama_down", "Ollama LLM server is unreachable — cloud fallback active", severity="warn")


async def _alert_mqtt(mqtt_connected: bool):
    if not mqtt_connected:
        _fire("mqtt_down", "MQTT broker disconnected — event bus offline", severity="critical")
    else:
        _clear("mqtt_down")


async def _alert_llm_latency():
    # Check last recorded p95 latency from Prometheus histogram
    from observability.metrics import llm_latency
    # If no samples yet, skip
    try:
        samples = list(llm_latency.collect()[0].samples)
        count_samples = [s for s in samples if s.name.endswith("_count") and s.labels.get("tier") == "1"]
        if not count_samples or count_samples[0].value == 0:
            return
        sum_samples = [s for s in samples if s.name.endswith("_sum") and s.labels.get("tier") == "1"]
        if sum_samples and count_samples:
            avg = sum_samples[0].value / count_samples[0].value
            if avg > 5.0:
                _fire("llm_latency_high", f"Average LLM latency {avg:.1f}s > 5s threshold", severity="warn")
            else:
                _clear("llm_latency_high")
    except Exception:
        pass


async def _alert_deadman():
    from observability.metrics import deadman_seconds_remaining
    try:
        remaining = deadman_seconds_remaining._value.get()
        if remaining == 0:
            return  # not configured yet
        pct = remaining / max(remaining, 1)
        if remaining < 120:
            _fire("deadman_critical", f"Dead man switch fires in {int(remaining)}s!", severity="critical")
        elif pct < 0.2:
            _fire("deadman_low", f"Dead man switch at {int(remaining)}s remaining", severity="warn")
        else:
            _clear("deadman_low")
            _clear("deadman_critical")
    except Exception:
        pass


# ── Background loop ──────────────────────────────────────────────────────────

async def run_alert_loop(get_mqtt_connected: Callable[[], bool], interval: int = 30):
    """Run all alert checks every `interval` seconds. Pass as asyncio background task."""
    log.info("alert_loop_started", interval_seconds=interval)
    while True:
        try:
            await asyncio.gather(
                _alert_redis(),
                _alert_ollama(),
                _alert_mqtt(get_mqtt_connected()),
                _alert_llm_latency(),
                _alert_deadman(),
            )
        except Exception as e:
            log.error("alert_loop_error", error=str(e))
        await asyncio.sleep(interval)
