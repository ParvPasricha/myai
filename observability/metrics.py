"""
Prometheus metrics for PARV-AI.

Import and instrument anywhere:
    from observability.metrics import (
        llm_latency, llm_requests, http_latency,
        mqtt_connected, brain_state_updates, alert_fires
    )
"""
from prometheus_client import (
    Counter, Histogram, Gauge, CollectorRegistry, REGISTRY
)

# ── LLM ─────────────────────────────────────────────────────────────────────
llm_requests = Counter(
    "parv_llm_requests_total",
    "Total LLM requests by tier and status",
    ["tier", "status"],
)

llm_latency = Histogram(
    "parv_llm_latency_seconds",
    "LLM inference latency in seconds",
    ["tier"],
    buckets=[0.5, 1, 2, 5, 10, 30, 60],
)

llm_queue_depth = Gauge(
    "parv_llm_queue_depth",
    "Number of LLM requests currently queued",
)

# ── HTTP ─────────────────────────────────────────────────────────────────────
http_requests = Counter(
    "parv_http_requests_total",
    "Total HTTP requests by method, path, status",
    ["method", "path", "status"],
)

http_latency = Histogram(
    "parv_http_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "path"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1, 2, 5],
)

# ── MQTT ─────────────────────────────────────────────────────────────────────
mqtt_connected = Gauge(
    "parv_mqtt_connected",
    "1 if MQTT broker is connected, 0 otherwise",
)

mqtt_messages_published = Counter(
    "parv_mqtt_messages_total",
    "Total MQTT messages published by topic prefix",
    ["topic_prefix"],
)

# ── Brain State ───────────────────────────────────────────────────────────────
brain_state_updates = Counter(
    "parv_brain_state_updates_total",
    "Total Brain State update calls",
)

brain_state_focus = Gauge("parv_brain_state_focus", "Current focus level 0-10")
brain_state_energy = Gauge("parv_brain_state_energy", "Current energy level 0-10")
brain_state_stress = Gauge("parv_brain_state_stress", "Current stress level 0-10")

# ── Infrastructure health ─────────────────────────────────────────────────────
redis_up = Gauge("parv_redis_up", "1 if Redis is reachable")
postgres_up = Gauge("parv_postgres_up", "1 if PostgreSQL is reachable")
ollama_up = Gauge("parv_ollama_up", "1 if Ollama is reachable")

# ── Security ──────────────────────────────────────────────────────────────────
deadman_seconds_remaining = Gauge(
    "parv_deadman_seconds_remaining",
    "Seconds until dead man switch triggers (0 = locked)",
)

# ── Alerts ───────────────────────────────────────────────────────────────────
alert_fires = Counter(
    "parv_alerts_total",
    "Total alerts fired by name",
    ["alert_name"],
)
