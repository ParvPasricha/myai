import asyncio
import time
from contextlib import asynccontextmanager

import paho.mqtt.client as mqtt
from fastapi import FastAPI, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST

from server.config import MQTT_HOST, MQTT_PORT, TAILSCALE_HOSTNAME
from server.auth import create_token, create_refresh_token, require_auth
from server.llm_router import llm
from server.routes.security import router as security_router
from server.routes.research import router as research_router
from server.routes.memory_routes import router as memory_router
from server.routes.speech import router as speech_router
from server.routes.vision import router as vision_router
from server.routes.dashboard import router as dashboard_router, broadcast_state
from server.routes.friends import router as friends_router
from server.routes.intelligence import router as intelligence_router, broadcast_intelligence
from server.routes.metrics_api import router as metrics_api_router
from server.routes.assistant import router as assistant_router
from server.routes.web_search import router as web_router
from server.routes.dream import router as dream_router, broadcast_dream
from server.routes.gdle import router as gdle_router
from server.routes.observe import router as observe_router
from server.routes.voice import router as voice_router
from server.routes.voice_editor import router as voice_editor_router
from server.routes.agents_route import router as agents_router, broadcast_agents
from server.routes.approval import router as approval_router
from observability.logger import log
from observability.metrics import (
    http_requests, http_latency,
    mqtt_connected as mqtt_connected_gauge,
    brain_state_updates, brain_state_focus, brain_state_energy, brain_state_stress,
)
from observability.healthcheck import full_health
from observability.alerts import run_alert_loop

# ── MQTT ─────────────────────────────────────────────────────────────────────
_mqtt_client: mqtt.Client | None = None
_mqtt_connected = False


def _on_connect(client, userdata, flags, reason_code, properties=None):
    global _mqtt_connected
    _mqtt_connected = reason_code == 0
    mqtt_connected_gauge.set(1 if _mqtt_connected else 0)
    log.info("mqtt_connect", connected=_mqtt_connected, host=MQTT_HOST, port=MQTT_PORT)


def _on_disconnect(client, userdata, disconnect_flags, reason_code, properties=None):
    global _mqtt_connected
    _mqtt_connected = False
    mqtt_connected_gauge.set(0)
    log.warn("mqtt_disconnect", reason=str(reason_code))


def mqtt_publish(topic: str, payload: str):
    if _mqtt_client and _mqtt_connected:
        _mqtt_client.publish(topic, payload)
        prefix = topic.split("/")[1] if "/" in topic else topic
        from observability.metrics import mqtt_messages_published
        mqtt_messages_published.labels(topic_prefix=prefix).inc()


# ── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    global _mqtt_client, _mqtt_connected

    # MQTT
    _mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="parv-ai-server")
    _mqtt_client.on_connect = _on_connect
    _mqtt_client.on_disconnect = _on_disconnect
    try:
        _mqtt_client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
        _mqtt_client.loop_start()
    except Exception as e:
        log.warn("mqtt_connect_failed", error=str(e))

    # Alert loop
    alert_task = asyncio.create_task(
        run_alert_loop(get_mqtt_connected=lambda: _mqtt_connected, interval=30)
    )

    # Dead man's switch loop
    from security.deadman import run_deadman_loop
    deadman_task = asyncio.create_task(run_deadman_loop(check_interval=10))

    # Backup scheduler
    from recovery.backup_scheduler import run_backup_scheduler
    backup_task = asyncio.create_task(run_backup_scheduler())

    # Research + quiz cron
    from research.scheduler import run_research_scheduler
    research_task = asyncio.create_task(run_research_scheduler())

    # Nightly memory distillation
    from memory.distill import run_distillation_scheduler
    distill_task = asyncio.create_task(run_distillation_scheduler())

    # Overwatcher — code graph + service health, polls every 30 s
    from intelligence.overwatcher import run_overwatcher
    from pathlib import Path
    overwatcher_task = asyncio.create_task(
        run_overwatcher(
            Path(__file__).parent.parent,
            broadcast_fn=broadcast_intelligence,
        )
    )

    # Dream scheduler — nightly at 3am, manual via POST /dream/run
    from intelligence.dream_scheduler import run_dream_scheduler
    dream_task = asyncio.create_task(
        run_dream_scheduler(broadcast_fn=broadcast_dream)
    )

    # Screen monitor — passive background observer every 30s
    from intelligence.screen_monitor import run_screen_monitor
    screen_task = asyncio.create_task(run_screen_monitor())

    # Jarvis proactive scheduler — speaks up when something needs attention
    from intelligence.jarvis_core import run_proactive_scheduler
    jarvis_task = asyncio.create_task(
        run_proactive_scheduler(broadcast_fn=broadcast_agents)
    )

    log.info("server_startup", service="parv-ai", version="0.5.0")

    yield

    tasks = [alert_task, deadman_task, backup_task, research_task,
             distill_task, overwatcher_task, dream_task, screen_task, jarvis_task]
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)   # wait for clean exit
    if _mqtt_client:
        _mqtt_client.loop_stop()
        _mqtt_client.disconnect()
    log.info("server_shutdown")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="PARV-AI", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:8000",
        f"http://{TAILSCALE_HOSTNAME}:3000",
        f"http://{TAILSCALE_HOSTNAME}:8000",
    ],
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

_start_time = time.time()
_bg_tasks: set[asyncio.Task] = set()   # keeps fire-and-forget tasks alive + logs exceptions

def _spawn(coro):
    t = asyncio.create_task(coro)
    _bg_tasks.add(t)
    t.add_done_callback(_bg_tasks.discard)
    return t

app.include_router(security_router)
app.include_router(research_router)
app.include_router(memory_router)
app.include_router(speech_router)
app.include_router(vision_router)
app.include_router(dashboard_router)
app.include_router(friends_router)
app.include_router(intelligence_router)
app.include_router(metrics_api_router)
app.include_router(assistant_router)
app.include_router(web_router)
app.include_router(dream_router)
app.include_router(gdle_router)
app.include_router(observe_router)
app.include_router(voice_router)
app.include_router(voice_editor_router)
app.include_router(agents_router)
app.include_router(approval_router)

# ── Request instrumentation middleware ────────────────────────────────────────
@app.middleware("http")
async def instrument(request: Request, call_next):
    t0 = time.time()
    response = await call_next(request)
    latency = time.time() - t0
    path = request.url.path
    method = request.method
    status = str(response.status_code)
    http_requests.labels(method=method, path=path, status=status).inc()
    http_latency.labels(method=method, path=path).observe(latency)
    log.info("http_request", method=method, path=path, status=status,
             latency_ms=round(latency * 1000))
    return response


# ── Web search helpers ────────────────────────────────────────────────────────
_WEB_TRIGGERS = {
    "latest", "current", "today", "right now", "news", "recently",
    "this week", "2026", "what happened", "who won", "price of",
    "stock", "weather", "trending", "just released", "announced",
    "update", "new version", "breaking",
}

def _needs_web_search(text: str) -> bool:
    lower = text.lower()
    return any(t in lower for t in _WEB_TRIGGERS)


async def _web_context(query: str) -> str:
    """Search web and return a short context block to inject into the prompt."""
    try:
        from server.routes.web_search import _ddg_search, _scrape
        results = await asyncio.to_thread(_ddg_search, query, 3)
        if not results:
            return ""
        # Scrape top result for full text
        top_text = await asyncio.to_thread(_scrape, results[0]["url"])
        lines = [f"[WEB — {r['title']}] {r['body'][:300]}" for r in results]
        if top_text:
            lines[0] = f"[WEB — {results[0]['title']}]\n{top_text[:1000]}"
        return "\n\n".join(lines)
    except Exception as e:
        log.warn("web_context_failed", error=str(e))
        return ""


# ── Background speech analysis ───────────────────────────────────────────────
async def _analyze_speech_bg(text: str, session_id: str):
    try:
        from intelligence.speech_analyzer import analyze
        from intelligence.conversation_logger import log_conversation
        metrics = analyze(text, source="chat")
        log_conversation(
            text=text,
            sentiment_label=metrics.get("sentiment_label", "neutral"),
            sentiment_score=metrics.get("sentiment_score", 0.0),
            session_id=session_id,
        )
    except Exception as e:
        log.debug("speech_bg_error", error=str(e))


# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/metrics")
async def metrics():
    """Prometheus scrape endpoint."""
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/health")
async def health():
    result = await full_health(mqtt_connected=_mqtt_connected)
    return result


@app.post("/auth/token")
async def get_token():
    """
    Dev-only endpoint — disabled in production (PARV_ENV=production).
    In production, tokens are issued via Face ID → JWT in the iOS app.
    """
    from server.config import ENV
    if ENV == "production":
        raise HTTPException(status_code=404, detail="Not found")
    return {
        "access_token": create_token(),
        "refresh_token": create_refresh_token(),
        "token_type": "bearer",
    }


@app.post("/ai/chat")
async def chat(body: dict, _auth: dict = Depends(require_auth)):
    import time as _time
    from memory import working, episodic
    from memory.context_builder import build_system_prompt

    prompt = body.get("prompt", "")
    base_system = body.get("system", "")
    session_id = body.get("session_id") or working.current_session()
    if not prompt:
        raise HTTPException(status_code=422, detail="prompt is required")

    # Log user message to episodic + working memory
    episodic.log_message(session_id, "user", prompt)
    working.append_message(session_id, "user", prompt)

    # Auto-analyze speech metrics for user messages (background, non-blocking)
    if len(prompt.split()) >= 5:   # skip very short commands
        _spawn(_analyze_speech_bg(prompt, session_id))

    # Build context-enriched system prompt
    system = build_system_prompt(prompt, session_id, base_system)

    # Auto-inject live web results for queries that need current info
    if _needs_web_search(prompt):
        web_ctx = await _web_context(prompt)
        if web_ctx:
            system += f"\n\n[LIVE WEB RESULTS]\n{web_ctx}"

    from observability.metrics import llm_latency, llm_requests
    t0 = _time.time()
    try:
        result = await llm.complete(prompt=prompt, system=system)
        latency = _time.time() - t0
        tier = str(result.get("tier", "?"))
        llm_latency.labels(tier=tier).observe(latency)
        llm_requests.labels(tier=tier, status="ok").inc()
        log.info("llm_response", tier=tier, latency_ms=round(latency * 1000),
                 model=result.get("model"))

        # Log assistant response
        response_text = result["text"]
        episodic.log_message(session_id, "assistant", response_text)
        working.append_message(session_id, "assistant", response_text)

        # Auto-learn from this conversation turn (background, non-blocking)
        from intelligence.learning_engine import learn_from_conversation
        _spawn(learn_from_conversation(session_id, prompt, response_text))

        mqtt_publish("parv/ai/response", response_text[:200])
        return {**result, "session_id": session_id}
    except Exception as e:
        llm_requests.labels(tier="?", status="error").inc()
        log.error("llm_error", error=str(e))
        raise HTTPException(status_code=503, detail=f"LLM error: {e}")


@app.get("/ai/status")
async def ai_status(_auth: dict = Depends(require_auth)):
    import httpx
    from server.config import OLLAMA_BASE_URL, OLLAMA_MODEL
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{OLLAMA_BASE_URL}/api/tags")
            ollama_ok = r.status_code == 200
            models = [m["name"] for m in r.json().get("models", [])] if ollama_ok else []
    except Exception:
        ollama_ok = False
        models = []
    return {"ollama": ollama_ok, "model": OLLAMA_MODEL, "available_models": models}


@app.get("/brain/state")
async def get_brain_state(_auth: dict = Depends(require_auth)):
    from intelligence.brain_state import get
    state = get()
    # Sync gauges
    brain_state_focus.set(state.get("focus", 0))
    brain_state_energy.set(state.get("energy", 0))
    brain_state_stress.set(state.get("stress", 0))
    return state


@app.patch("/brain/state")
async def patch_brain_state(body: dict, _auth: dict = Depends(require_auth)):
    from intelligence.brain_state import update
    state = update(body)
    brain_state_updates.inc()
    brain_state_focus.set(state.get("focus", 0))
    brain_state_energy.set(state.get("energy", 0))
    brain_state_stress.set(state.get("stress", 0))
    mqtt_publish("parv/brain/state_update", "updated")
    log.info("brain_state_updated", patch=list(body.keys()))
    _spawn(broadcast_state())   # push to dashboard WebSocket clients
    return state
