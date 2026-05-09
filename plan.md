

     A comprehensive personal AI system built around a central "brain" running on a Windows laptop (i7 9th gen, GTX 1650 4GB VRAM, 32GB RAM, 1.5TB) that later migrates to Raspberry Pi 5. The system monitors, learns from, and improves Parv
     across all aspects of life — habits, speech, emotions, productivity, item tracking, and knowledge acquisition — with a security-first, event-driven architecture and strict AI authority rules.

     Core Principles:
     - AI proposes. Human approves. (Unless explicitly whitelisted.)
     - Everything communicates through MQTT. No direct cross-service logic.
     - Reliability before features. Observability before complexity.
     - Progressive rollout over heroic first-day completeness.

     ---
     Hardware & Compute Tiers

     ┌───────────────┬─────────────────────────────────────────────────┬─────────────────────────────────────────────────┐
     │     Tier      │                    Hardware                     │                      Role                       │
     ├───────────────┼─────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
     │ Primary (now) │ Windows laptop (i7-9th, GTX 1650 4GB, 32GB RAM) │ Main brain, runs all services                   │
     ├───────────────┼─────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
     │ Mobile edge   │ iPhone + AirPods                                │ STT, camera, UI, sensors                        │
     ├───────────────┼─────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
     │ Biosensor     │ Muse S EEG headband (Phase 10)                  │ Brainwave data: focus, stress, relaxation, flow │
     ├───────────────┼─────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
     │ Future        │ Raspberry Pi 5 8GB + Hailo AI HAT+ 2 (Phase 11) │ Always-on hub; laptop becomes GPU offload       │
     ├───────────────┼─────────────────────────────────────────────────┼─────────────────────────────────────────────────┤
     │ Cloud         │ Claude API + OpenAI API                         │ Heavy reasoning, code generation                │
     └───────────────┴─────────────────────────────────────────────────┴─────────────────────────────────────────────────┘

     Physical Kill Switch (Mandatory Hardware Rule): A physical switch (or switched power strip) must be wired to cut power to cameras, microphones, and automation systems. Not software. Real hardware. This is non-negotiable for a system with
     always-on sensors.

     ---
     System Architecture

     [iPhone Edge]
       ↕ Tailscale (primary) / .onion Tor (Phase 9 fallback)
     [Laptop Brain]
       ├── Brain State (/intelligence/brain_state.py) ← single source of truth
       ├── MQTT Bus (Mosquitto) ← ALL subsystems publish/subscribe here
       ├── LLM Server (Ollama + CUDA)
       ├── Memory System (4-layer)
       ├── Security + Recovery Layer
       ├── Observability (Prometheus + Grafana)
       └── FastAPI Hub (reads Brain State, routes requests)
             ↕ Cloud AI (Claude/GPT) for heavy tasks

     Two-sided communication: AI pushes to iPhone proactively (APNS/WebSocket), not only responds to requests.

     ---
     Brain State: The Real AI Core

     File: /intelligence/brain_state.py

     Single source of truth. Every subsystem reads from and writes to this. The LLM is a tool; this is the brain.

     {
       "focus": 8,
       "energy": 6,
       "stress": 4,
       "deep_work": true,
       "social_mode": false,
       "learning_mode": "physics",
       "security_state": "armed",
       "current_activity": "coding",
       "location": "home/desk",
       "mic_stage": "push_to_talk",
       "brainwave": {
         "alpha": 0.42,
         "beta": 0.31,
         "theta": 0.18,
         "delta": 0.06,
         "gamma": 0.03,
         "focus_index": 0.74,
         "relaxation_index": 0.55,
         "source": "muse_s"
       }
     }

     brainwave field is null until Phase 10 hardware is connected. All subsystems must handle its absence gracefully.

     Backed by Redis (live) + PostgreSQL (historical snapshots every 15min).

     ---
     MQTT Event Bus: The Communication Rule

     Broker: Mosquitto on laptop, port 1883.

     Rule: NO direct cross-service function calls. Everything publishes an event. Everything subscribes to what it needs.

     Event topics:
     parv/brain/state_update
     parv/emotion/detected
     parv/focus/drop
     parv/item/seen
     parv/speech/analyzed
     parv/quiz/completed
     parv/security/deadman_warning
     parv/security/lockdown
     parv/user/arrived_home
     parv/research/topic_assigned
     parv/camera/face_recognized
     parv/ai/suggestion
     parv/brainwave/raw_bands
     parv/brainwave/focus_index
     parv/brainwave/state_change
     parv/brainwave/anomaly
     parv/intent/extracted
     parv/intent/corrected
     parv/suggestion/received
     parv/understanding/confirmed

     FastAPI exposes a WebSocket bridge: iPhone subscribes to relevant topics without needing MQTT directly.

     ---
     AI Authority Rules

     File: /intelligence/authority_rules.py

     ┌───────────────────────────────────────────────┬────────────────────────────────────────┐
     │                    AI CAN                     │               AI CANNOT                │
     ├───────────────────────────────────────────────┼────────────────────────────────────────┤
     │ Suggest, notify, recommend, warn              │ Silently decide or act                 │
     ├───────────────────────────────────────────────┼────────────────────────────────────────┤
     │ Propose schedule changes                      │ Auto-change schedules without approval │
     ├───────────────────────────────────────────────┼────────────────────────────────────────┤
     │ Flag a productivity issue                     │ Block an app without explicit trigger  │
     ├───────────────────────────────────────────────┼────────────────────────────────────────┤
     │ Initiate deadman lockdown if hard trigger met │ Trigger lockdown speculatively         │
     ├───────────────────────────────────────────────┼────────────────────────────────────────┤
     │ Push quiz at scheduled time                   │ Skip or reschedule quiz silently       │
     └───────────────────────────────────────────────┴────────────────────────────────────────┘

     Hard triggers (explicit whitelist, pre-approved by user):
     - Deadman timer expiry → lockdown
     - Scheduled 6am topic push → no approval needed
     - Scheduled 10pm quiz → no approval needed
     - "Focus block" during pre-approved deep work windows

     Everything else: propose → user approves via app tap.

     ---
     Intent Understanding System (Active from Phase 3)

     Goal: Every input — text, voice, or suggestion — is not just stored raw but understood, categorized into structured recallable knowledge, and actively corrected when the AI gets it wrong. The AI learns your intent model over time.

     How It Works

     Every user input goes through a pipeline before reaching the LLM or memory:

     [user input: text / voice transcript / suggestion]
             ↓
     /intelligence/intent_extractor.py
             ↓
     {action, category, entities, confidence, raw_text}
             ↓
     → stored in PostgreSQL intent_log table
     → embedded in ChromaDB for semantic recall
     → published to parv/intent/extracted
             ↓
     AI echoes its understanding back to user:
     "Got it — I understood this as: [preference: you want alarms 30min earlier on gym days]"
             ↓
     User confirms (tap ✓) OR corrects (tap ✗ + says what was wrong)
             ↓
     /intelligence/correction_handler.py updates the record
     → publishes parv/intent/corrected
     → re-embeds corrected understanding in ChromaDB
     → increments correction_count for this intent type (feeds future accuracy)

     Intent Categories

     ┌─────────────┬────────────────────────────────────────┬──────────────────────────────────────────────────┐
     │  Category   │                Example                 │                    Stored As                     │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ preference  │ "I like working out before lunch"      │ user preference fact                             │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ habit       │ "I always check my phone after waking" │ habit pattern                                    │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ task        │ "remind me to call dad on Sunday"      │ structured task                                  │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ correction  │ "no, I meant 9pm not 9am"              │ correction record linked to prior intent         │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ feedback    │ "that suggestion was wrong"            │ negative signal for suggestion engine            │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ command     │ "block Reddit until quiz is done"      │ immediate action (requires authority rule check) │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ observation │ "I feel tired today"                   │ self-reported state → updates Brain State        │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ goal        │ "I want to read 2 books a month"       │ long-term goal record                            │
     ├─────────────┼────────────────────────────────────────┼──────────────────────────────────────────────────┤
     │ context     │ "I'm going to Delhi for 3 days"        │ temporal context fact                            │
     └─────────────┴────────────────────────────────────────┴──────────────────────────────────────────────────┘

     Correction Learning

     When user corrects the AI:
     1. Original intent record marked corrected: true
     2. Corrected version stored linked to original (corrected_from_id)
     3. LLM generates a "lesson": "When user says X in context Y, they mean Z, not W"
     4. Lesson stored in ChromaDB under intent_lessons collection
     5. Future intent extraction: relevant lessons retrieved and injected as few-shot examples into the extraction prompt
     6. correction_count per intent category tracked → categories with high corrections get more careful extraction (higher temperature, rephrasing back to user more often)

     Recallable Data Structure (PostgreSQL)

     intent_log(
       id, timestamp, raw_text, source,       -- text/voice/suggestion
       category, action, entities_json,        -- extracted structure
       confidence, corrected, corrected_from,  -- quality tracking
       embedding_id                            -- ChromaDB pointer
     )

     intent_lessons(
       id, timestamp, context, wrong_interpretation,
       correct_interpretation, lesson_text, embedding_id
     )

     Query Examples (natural language → SQL/vector)

     - "What are my stated preferences about sleep?" → semantic search category=preference + entities.topic=sleep
     - "What tasks did I mention this week?" → SQL category=task AND timestamp > 7 days ago
     - "What have I been correcting the AI about most?" → GROUP BY category ORDER BY correction_count DESC

     Files

     - /intelligence/intent_extractor.py — LLM-based structured extraction from any input
     - /intelligence/correction_handler.py — correction detection, lesson generation, ChromaDB update
     - /intelligence/intent_recall.py — query interface: natural language → structured memory lookup
     - /server/routes/intent.py — POST /intent/submit, POST /intent/correct, GET /intent/recall
     - iOS Views/IntentFeedbackView.swift — echoed understanding card with ✓/✗ tap + voice correction

     Integration Points

     - Memory system (Phase 5): Intent log is the 5th structured table in PostgreSQL alongside habits/items/emotions
     - Context builder: Top-5 most relevant past intents + lessons injected into every LLM context block
     - Speech analyzer (Phase 6): Voice input flows through intent extractor before storage — same pipeline
     - Brain State: observation category intents directly update Brain State fields (energy, stress, mood)
     - Authority rules: command category intents checked against whitelist before acting

     ---
     Phase 0: Core Infrastructure

     Goal: Reliable, observable backbone before any feature work.

     Steps

     1. Install Ollama + CUDA on Windows — pull llama3.2:7b-instruct-q4_K_M (fits in GTX 1650 4GB VRAM)
     2. FastAPI backend (/server/main.py) — central API hub, reads Brain State for every response
     3. LiteLLM proxy (/server/llm_router.py) — routes: local Ollama → CPU fallback → Claude API → OpenAI based on load + task type
     4. Tailscale — install on laptop + iPhone. iPhone reaches laptop at stable Tailscale hostname
     5. JWT auth — all endpoints require Bearer token. Face ID on iPhone generates auth request → laptop issues JWT (1hr expiry + refresh)
     6. Mosquitto MQTT broker — all subsystems connect here. FastAPI WebSocket bridge for iPhone

     Files

     - /server/main.py — FastAPI root
     - /server/llm_router.py — tiered LLM routing
     - /server/config.py — env config (API keys, Tailscale hostname, MQTT address)
     - /server/auth.py — JWT issue + verify

     Verification

     - curl http://localhost:8000/health → {"status": "ok"}
     - curl http://<tailscale-ip>:8000/health → works from iPhone hotspot
     - MQTT broker accepts connection: mosquitto_pub -t parv/test -m hello

     ---
     Phase 1: Observability

     Goal: Know exactly what failed, where, and why — before building anything complex.

     Stack

     - Prometheus — scrapes metrics from all services
     - Grafana — dashboards for system health, latency, queue depth, inference timing
     - Structured JSON logs — every service logs {timestamp, service, level, event, latency_ms, error}

     Metrics to track

     - LLM inference latency (p50, p95, p99)
     - MQTT queue depth per topic
     - Redis memory usage
     - PostgreSQL query latency
     - FastAPI request latency per endpoint
     - Service restart events (systemd/supervisord integration)
     - Brain State update frequency
     - Deadman ping timestamps

     Alerts (via Grafana alerting → push notification to iPhone)

     - Any service down > 30s
     - Redis/Postgres unreachable
     - LLM inference latency > 5s
     - MQTT broker disconnect
     - Deadman timer < 20% remaining
     - Model inference queue > 10 items

     Files

     - /observability/metrics.py — Prometheus metric definitions (counters, histograms, gauges)
     - /observability/logger.py — structured JSON logger (wraps Python logging)
     - /observability/healthcheck.py — /health endpoint aggregating all subsystem checks
     - /observability/alerts.py — alert rule evaluator + APNS push sender

     Verification

     - Grafana dashboard shows LLM latency graph
     - Kill Redis → alert push notification arrives on iPhone within 60s
     - /health endpoint returns per-subsystem status

     ---
     Phase 2: Security + Recovery

     Goal: All data encrypted. Emergency lockdown works. Daily backups with verified restore.

     AES-256 Encryption

     - Master password → PBKDF2-SHA256 (100k iterations, random salt) → 256-bit AES-GCM key
     - All databases, memory files, conversation logs encrypted at rest
     - Key held in RAM only; never written to disk
     - On startup: prompt for master password → derive key → decrypt data
     - Payload encrypter (/security/encrypter.py): CLI + API to encrypt/decrypt arbitrary data bundles

     Dead Man's Switch

     - iPhone app sends /security/ping heartbeat every N minutes (configurable: 15min–24h)
     - RAM-only last_ping_timestamp variable (not persisted)
     - Background thread: if now - last_ping > threshold → lockdown sequence:
       a. Publish parv/security/lockdown to MQTT
       b. All services encrypt their data files
       c. Wipe master key from RAM
       d. Stop all services
       e. Append to encrypted audit log
       f. Push notification: "System locked — re-authenticate"
     - Failure diagnosis: Observability layer logs why ping stopped (network? iPhone crash? battery?)

     Recovery Layer

     Daily automated backup workflow:

     snapshot → verify integrity → encrypt → store backup

     - /recovery/snapshot.py — dumps all databases + ChromaDB to a versioned archive
     - /recovery/verify.py — checksums every file in the snapshot, reports corruption
     - /recovery/restore.py — decrypts + restores a named snapshot, verifies post-restore integrity
     - /recovery/backup_scheduler.py — cron: 3am daily snapshot + weekly restore test (dry run)

     Snapshots stored in /backups/ directory. Keep last 30 days. Oldest pruned automatically.

     Ping Monitor + Timer

     - GET /security/status → {last_ping, threshold_minutes, time_remaining_seconds, locked, locked_at}
     - PATCH /security/timer → update threshold
     - iPhone app shows countdown widget on home screen

     Tor Hidden Service (Deferred to Phase 9)

     Tailscale handles remote access. Tor added later as privacy fallback once system is stable.

     Files

     - /security/crypto.py — AES-256-GCM + PBKDF2
     - /security/encrypter.py — payload encrypter CLI + API
     - /security/deadman.py — ping tracker + lockdown trigger
     - /security/audit.py — encrypted append-only audit log
     - /recovery/snapshot.py, verify.py, restore.py, backup_scheduler.py

     Verification

     - Encrypt test DB, restart, verify unreadable → enter password → decrypts correctly
     - Stop ping, wait for timer → lockdown triggers → push notification arrives
     - Run restore from yesterday's snapshot → verify all data intact

     ---
     Phase 3: iPhone App (Basic)

     Goal: Reliable iPhone interface with push-to-talk, status monitoring, and notifications. No always-on mic yet.

     Mic Stage 1: Push-to-Talk

     Hold button → record → WhisperKit transcribes locally (Core ML, ANE) → POST to FastAPI.
     No background audio, no VoIP mode, no iOS complexity.

     Core Features

     - Face ID → JWT auth via LocalAuthentication framework
     - Push-to-talk voice input with WhisperKit on-device STT
     - WebSocket subscription to Brain State updates + AI suggestion pushes
     - Ping heartbeat — configurable background timer, keeps dead man's switch alive
     - Security status widget — ping countdown, lock state, system health (from /health)
     - Notification handler — AI proposals arrive as push notifications; user taps Approve/Dismiss

     Key Screens

     1. Home — Brain State display (focus, energy, stress), current activity, today's research topic
     2. Chat — push-to-talk → AI response
     3. Status — ping timer, system health per subsystem, Tailscale connection state
     4. Settings — ping interval, approved friend list, mic stage setting

     Tailscale + JWT Connection

     - App uses Tailscale hostname (configured at setup)
     - All requests: Authorization: Bearer <jwt>
     - Connection manager: LAN direct → Tailscale. .onion path deferred to Phase 9.

     Files (/ios/ParvAI/)

     - Services/AudioService.swift — WhisperKit STT, push-to-talk session
     - Services/ConnectionManager.swift — Tailscale connection, WebSocket, JWT refresh
     - Services/PingService.swift — background heartbeat timer
     - Views/HomeView.swift, ChatView.swift, StatusView.swift
     - Auth/FaceIDAuth.swift — LocalAuthentication → JWT flow

     Verification

     - App transcribes voice locally < 1s latency
     - Push notification from laptop AI arrives and shows Approve/Dismiss
     - Ping heartbeat keeps dead man's switch alive
     - Kill Tailscale on laptop → app shows "disconnected" in status within 30s

     ---
     Phase 4: Research + Quiz Loop (Dopamine Mechanic)

     Goal: Daily topic → research → end-of-day quiz → score. Highest immediate ROI on quality of life.

     Flow

     1. 6am cron → LLM generates today's topic based on:
       - Past quiz weak-score areas (from PostgreSQL)
       - Knowledge gaps detected in conversations
       - User-defined interest domains
     2. Publishes parv/research/topic_assigned to MQTT
     3. FastAPI pushes topic to iPhone via WebSocket — shown as "Today's Mission"
     4. Throughout day: AI captures research context from conversations (STT transcripts tagged with topic)
     5. Optional browser companion: HTTP endpoint /research/log accepts page title + summary POSTs
     6. 8pm reminder push notification: "Quiz in 2 hours"
     7. 10pm quiz — LLM generates 10-15 questions, pushes to iPhone
     8. Answers evaluated by LLM, score 0-100 stored in PostgreSQL
     9. Score displayed with streak counter + XP bar (dopamine hit)
     10. Score feeds next topic selection — weak areas revisited

     Files

     - /research/topic_generator.py — quiz-history-aware LLM topic selection
     - /research/quiz_engine.py — question generation + answer evaluation + scoring
     - /server/routes/research.py — topic, log, quiz submit, leaderboard endpoints
     - iOS Views/ResearchView.swift — topic display, quiz UI, score reveal with animation

     Verification

     - 6am cron fires → topic appears in iPhone app
     - Submit quiz answers → score saved in PostgreSQL
     - Next day's topic avoids recently high-scored areas, revisits low scores

     ---
     Phase 5: Memory System

     Goal: AI remembers everything across sessions. Context is always personalized.

     Four-Layer Architecture

     ┌────────────┬─────────────────────┬─────────┬─────────────────────────────────────────────────┐
     │   Layer    │        Store        │   TTL   │                    Contents                     │
     ├────────────┼─────────────────────┼─────────┼─────────────────────────────────────────────────┤
     │ Working    │ Redis               │ 24h     │ Active session, last 10 exchanges               │
     ├────────────┼─────────────────────┼─────────┼─────────────────────────────────────────────────┤
     │ Episodic   │ SQLite + FTS5       │ Forever │ All conversations with timestamps               │
     ├────────────┼─────────────────────┼─────────┼─────────────────────────────────────────────────┤
     │ Semantic   │ ChromaDB (embedded) │ Forever │ Summaries as vector embeddings                  │
     ├────────────┼─────────────────────┼─────────┼─────────────────────────────────────────────────┤
     │ Structured │ PostgreSQL          │ Forever │ Habits, item locations, emotion logs, decisions │
     └────────────┴─────────────────────┴─────────┴─────────────────────────────────────────────────┘

     Nightly Distillation Cron (/memory/distill.py)

     1. Summarize last 24h conversations via local LLM
     2. Extract structured facts: decisions, items placed, emotional patterns
     3. Embed summary → ChromaDB (model: all-MiniLM-L6-v2, 90MB)
     4. Write extracted facts → PostgreSQL
     5. Clear Redis working memory
     6. Snapshot Brain State to PostgreSQL historical table

     Context Injection (/memory/context_builder.py)

     Every LLM call prepends: Redis working memory + top-3 ChromaDB semantic matches + relevant PostgreSQL facts. Target: ~2000 token context block.

     Files

     - /memory/working.py — Redis read/write
     - /memory/episodic.py — SQLite + FTS5 conversation logger
     - /memory/semantic.py — ChromaDB embed + query
     - /memory/structured.py — PostgreSQL habits/items/emotions schema
     - /memory/distill.py — nightly distillation
     - /memory/context_builder.py — multi-layer context assembly

     Verification

     - Ask AI about yesterday's conversation → recalls correctly
     - "Where did I last see my wallet?" → returns zone + timestamp
     - Nightly cron runs → ChromaDB has new embeddings
     - Brain State history queryable: "When was my last high-focus period?"

     ---
     Phase 6: Speech Improvement AI

     Goal: Track and improve vocabulary, filler words, speaking pace, and conversation quality.

     Pipeline

     1. STT transcripts (from push-to-talk or future mic stages) → /intelligence/speech_analyzer.py
     2. Analysis: filler words (um/uh/like/you know), vocabulary richness (type-token ratio), words per minute, sentence complexity
     3. Person + topic extraction: who was mentioned, what topic, what mood
     4. Weekly report pushed to iPhone: "34% fewer filler words this week. Pace: 142 WPM."
     5. Publishes parv/speech/analyzed to MQTT → Brain State stress + energy updated from tone markers

     Conversation Context Memory

     When a person's name is detected: log {name, topic, date, sentiment} in PostgreSQL.
     Query: "When did I last talk to Rohan?" → "12 days ago, about the internship."

     Mic Stage Progression (user-controlled in app settings)

     - Stage 1 (Phase 3): Push-to-talk — active now
     - Stage 2 (unlock manually): Wake phrase detection ("Hey Parv") — no background drain
     - Stage 3 (unlock manually): Passive context mode — mic on during set hours only
     - Stage 4 (unlock manually): VoIP persistent always-on — full iOS VoIP mode, requires $99 dev account + sideload

     Each stage unlocked by user explicitly in Settings. No auto-progression.

     Files

     - /intelligence/speech_analyzer.py — transcript analysis + metrics
     - /intelligence/conversation_logger.py — person/topic/sentiment extraction
     - /server/routes/speech.py — weekly report endpoint

     ---
     Phase 7: Vision Pipeline

     Goal: Cameras identify Parv, detect emotions, track item locations, infer behavioral patterns.

     Camera Pipeline

     1. RTSP ingestion — GStreamer decodes IP camera streams
     2. Face recognition — InsightFace + ArcFace (ONNX Runtime, CUDA on GTX 1650)
       - Known embeddings in SQLite; cosine similarity > 0.6 threshold
     3. Emotion detection — FER+ ONNX model
       - Detects: happy, sad, angry, neutral, focused, tired, stressed
       - Logs {timestamp, emotion, confidence} → PostgreSQL + updates Brain State
     4. Object detection — YOLOv11n (Ultralytics, GPU)
       - Room zones defined by one-time calibration (polygon draw over reference frame)
       - Item tracking: {object_class, zone, first_seen, last_seen} in SQLite
     5. Behavior inference — nightly LLM analysis of emotion timeline:
       - "You appear tired after 11pm — correlates with poor quiz scores next day"
       - "Stress spikes on Wednesday afternoons — calendar event: algo practice"

     All camera events published as MQTT topics (parv/camera/face_recognized, parv/emotion/detected, parv/item/seen).

     Files

     - /vision/camera_pipeline.py — RTSP → InsightFace → YOLOv11n → zone mapper
     - /vision/emotion_tracker.py — FER inference + MQTT publish + PostgreSQL write
     - /vision/item_tracker.py — zone-based item memory + query API
     - /intelligence/behavior.py — pattern analysis → Brain State + suggestion generation

     Verification

     - Camera detects face → logs identity < 2s → MQTT event fires
     - "Where are my headphones?" → correct zone + last-seen timestamp
     - After 3 days: behavior API returns at least 1 actionable suggestion

     ---
     Phase 8: WhatsParvDoing Dashboard

     Goal: Real-time public dashboard — approved friends see current activity, focus, location.

     Stack

     - Backend: FastAPI routes + Redis pub/sub → WebSocket fanout
     - Frontend: Next.js 15 + Tailwind CSS + Leaflet.js
     - Auth: JWT friend tokens — Parv issues signed links, no registration required
     - Real-time: WebSocket push when Brain State changes
     - Hosting: Nginx on laptop → FastAPI (8000) + Next.js (3000)

     Dashboard payload

     {
       "current_activity": "deep work / coding",
       "focus_score": 8,
       "emotion": "focused",
       "location": "home / desk",
       "today_topic": "Transformer Architecture",
       "quiz_status": "pending",
       "last_updated": "2026-05-05T14:32:00Z"
     }

     Friends see this. Nothing sensitive (no item locations, no conversation content, no security state).

     Files

     - /dashboard/frontend/ — Next.js app
     - /server/routes/dashboard.py — WebSocket + REST
     - /server/routes/friends.py — token issuance + validation

     ---
     Phase 9: Tor Hidden Service (Remote Access Fallback)

     Goal: Privacy-maximized remote access when Tailscale is unavailable or untrusted network.

     - Install Tor daemon on Windows; configure torrc to expose FastAPI port 8000 as .onion
     - Store .onion address in iPhone app config
     - iPhone uses Orbot iOS app as SOCKS5 proxy to route to .onion
     - Connection manager priority: LAN direct → Tailscale → .onion via Orbot
     - Tor added here (not Phase 0) because it is a debugging sink. Build on stable Tailscale first.

     ---
     Phase 12: Brainwave Scanner

     Goal: Add physiological ground truth for mood, focus, and cognitive state — the highest-fidelity signal in the entire system. Combined with camera emotion detection, this creates multi-modal behavioral understanding no camera or microphone
      can match.

     Hardware Options (pick one)

     ┌──────────────────────┬───────┬──────────┬────────────┬────────────────┬───────────────────────────────────────────────┐
     │        Device        │ Price │ Channels │    BLE     │    Accuracy    │                     Notes                     │
     ├──────────────────────┼───────┼──────────┼────────────┼────────────────┼───────────────────────────────────────────────┤
     │ Muse S (recommended) │ ~$300 │ 4 EEG    │ Yes        │ Good           │ Consumer, comfortable, proven Python SDK      │
     ├──────────────────────┼───────┼──────────┼────────────┼────────────────┼───────────────────────────────────────────────┤
     │ Muse 2               │ ~$200 │ 4 EEG    │ Yes        │ Good           │ Older, still works, slightly less comfortable │
     ├──────────────────────┼───────┼──────────┼────────────┼────────────────┼───────────────────────────────────────────────┤
     │ OpenBCI Cyton        │ ~$500 │ 8 EEG    │ USB dongle │ Research-grade │ Best data, awkward form factor                │
     ├──────────────────────┼───────┼──────────┼────────────┼────────────────┼───────────────────────────────────────────────┤
     │ DIY (ADS1299)        │ ~$50  │ 8 EEG    │ Custom     │ Variable       │ Cheapest, most effort                         │
     └──────────────────────┴───────┴──────────┴────────────┴────────────────┴───────────────────────────────────────────────┘

     Recommended starting point: Muse S — BLE to laptop/iPhone, 4 channels sufficient for focus/stress/relaxation detection, well-supported by BrainFlow.

     EEG Band Reference

     ┌───────┬──────────┬──────────────────────────────────────┐
     │ Band  │ Hz Range │                State                 │
     ├───────┼──────────┼──────────────────────────────────────┤
     │ Delta │ 0.5–4    │ Deep sleep                           │
     ├───────┼──────────┼──────────────────────────────────────┤
     │ Theta │ 4–8      │ Drowsy, meditative, creative         │
     ├───────┼──────────┼──────────────────────────────────────┤
     │ Alpha │ 8–13     │ Calm, relaxed, eyes-closed rest      │
     ├───────┼──────────┼──────────────────────────────────────┤
     │ Beta  │ 13–30    │ Active thinking, focused, stressed   │
     ├───────┼──────────┼──────────────────────────────────────┤
     │ Gamma │ 30–100   │ High cognition, learning, flow state │
     └───────┴──────────┴──────────────────────────────────────┘

     Software Pipeline (/brainwave/)

     1. BrainFlow (brainflow Python library) — unified API for all supported EEG devices. Connects via BLE (Muse) or serial (OpenBCI). Streams 250Hz raw EEG samples.
     2. Band power extraction (/brainwave/processor.py):
       - FFT on 2-second windows with 50% overlap
       - Compute power in each band per channel
       - Focus index: beta / (alpha + theta) — higher = more focused
       - Relaxation index: alpha / (alpha + beta) — higher = calmer
       - Stress index: high beta + low alpha
     3. State classifier (/brainwave/classifier.py):
       - scikit-learn Random Forest trained on labeled sessions (user labels their state manually for first 2 weeks to build personal baseline)
       - Outputs: {focus, relaxation, stress, drowsy, flow_state} scores 0-1
       - Personal model stored in /models/brainwave_personal.pkl — improves over time
     4. MQTT publisher: Publishes parv/brainwave/raw_bands (10Hz), parv/brainwave/focus_index (1Hz), parv/brainwave/state_change on transitions
     5. Brain State updater: Subscribes to brainwave events → updates brain_state.brainwave in Redis
     6. Fusion layer (/intelligence/mood_fusion.py): Combines brainwave state + camera emotion + speech tone into a single fused mood estimate. Brainwave has highest weight (physiological > behavioral).

     Improvement Loop

     - Nightly distillation includes brainwave patterns:
       - "Flow state detected 3x this week, always 10am–noon after coffee"
       - "Stress spikes detected before your 6pm calls — consistently"
     - Suggestions pushed to iPhone: "Your focus index is 0.82 right now — this is your peak window. Starting deep work block."
     - Drowsiness detected → "You've been drowsy for 20min. 10-min walk suggested."
     - Low energy + high stress → "Break recommended. No quiz questions right now."

     Calibration Protocol (first use)

     1. 5-minute baseline: eyes open, neutral
     2. 5-minute focus task: read an article
     3. 5-minute relaxation: breathe slowly
     4. Label each session in app → personal baseline established

     Files

     - /brainwave/stream.py — BrainFlow device connect + raw sample stream
     - /brainwave/processor.py — FFT band power extraction, focus/stress indices
     - /brainwave/classifier.py — personal scikit-learn classifier, training + inference
     - /brainwave/calibration.py — guided calibration protocol + baseline storage
     - /intelligence/mood_fusion.py — multi-modal mood fusion (brainwave + camera + speech)
     - /server/routes/brainwave.py — calibration start/stop, current state, history endpoints

     Verification

     - BrainFlow connects to Muse S, streams data
     - Band power values change measurably between eyes-open and eyes-closed
     - Focus index rises during active coding vs. YouTube
     - Brain State updated with brainwave data within 2s of state change
     - Mood fusion returns combined estimate correctly weighted

     ---
     Phase 10: Pi Migration

     When: After Raspberry Pi 5 (8GB) + Hailo AI HAT+ 2 purchased.

     Migration Strategy: Service-by-Service, Not Big Bang

     Migrate one service at a time. Verify each on Pi before cutting over. Laptop stays as hot fallback throughout.

     Hardware to Buy

     - Raspberry Pi 5 8GB
     - Hailo AI HAT+ 2 (40 TOPS M.2 module) — for YOLOv11n + InsightFace at 30+ FPS
     - 128GB+ high-endurance microSD (Samsung PRO Endurance) or NVMe via USB3
     - PoE HAT (optional) — powers Pi from the same cable as PoE cameras
     - Active cooler (Pi 5 runs hot under sustained AI load)

     Migration Order

     Step 1 — Pi baseline:
     - Install Raspberry Pi OS Lite (64-bit), headless
     - Install Tailscale on Pi → joins existing Tailscale network
     - Verify SSH from laptop + iPhone

     Step 2 — MQTT migration:
     - Install Mosquitto on Pi
     - Update all subsystem configs to point to Pi MQTT broker
     - Verify all MQTT events flow correctly
     - Decommission laptop Mosquitto

     Step 3 — Lightweight FastAPI services:
     - Move /server/routes/security.py, /server/routes/research.py, /server/routes/dashboard.py to Pi
     - Pi runs FastAPI on port 8000 via systemd service
     - Laptop FastAPI becomes localhost-only (for heavy LLM routes only)
     - Update iPhone connection manager to route to Pi Tailscale address

     Step 4 — Vision pipeline:
     - Install Hailo AI HAT+ 2 + Hailo SDK on Pi
     - Compile YOLOv11n + InsightFace for Hailo runtime
     - Move /vision/ to Pi — cameras now stream to Pi, not laptop
     - Laptop no longer needed for vision

     Step 5 — LLM architecture change:
     - Pi runs llama.cpp --server with Gemma3:1b or Qwen2.5:0.5b (fast, low RAM)
     - Laptop runs llama.cpp --rpc as a tensor offload server (GPU muscle on demand)
     - LiteLLM router updated: Pi LLM (fast/simple) → laptop RPC offload (medium) → Cloud (heavy)
     - Pi handles 80% of requests; laptop GPU only used for complex tasks

     Step 6 — Memory + storage:
     - Move PostgreSQL + Redis + ChromaDB + SQLite to Pi (NVMe for speed)
     - Update connection strings across all services
     - Run one final sync from laptop DBs to Pi DBs
     - Verify nightly distillation cron runs correctly on Pi

     Step 7 — Cleanup:
     - Decommission laptop as primary brain
     - Laptop becomes pure GPU offload node (stays on, llama.cpp RPC running)
     - Add PiVPN (WireGuard) to Pi as backup VPN alongside Tailscale
     - Update Tor hidden service to run on Pi

     Rollback Plan

     Each step keeps laptop running as fallback. If Pi step fails: point configs back to laptop, debug Pi independently, retry.

     Verification

     - All MQTT events still flow after each migration step
     - FastAPI health endpoint returns correct on Pi address
     - Vision pipeline detects faces at 30+ FPS (Hailo-accelerated)
     - LLM responds from Pi at 15+ tok/s
     - iPhone app seamlessly uses Pi as brain

     ---
     Phase 11: Smart Glasses (Very Late)

     Hardware: XIAO ESP32-S3 Sense (built-in camera + mic + BLE). Reference: OpenGlass (BasedHardware, open source).

     Features:
     - BLE → iPhone: frames forwarded to laptop for InsightFace recognition
     - Recognized person → name + last conversation date + topic → whispered via bone conduction speaker
     - Bypasses all iOS mic restrictions — hardware BLE data, not iOS microphone API

     Why very late: Hardware prototyping, BLE latency tuning, and face recognition feedback loop all have independent debugging cycles. Only makes sense after the software brain is fully stable.

     ---
     Security Architecture Summary

     ┌────────────────────┬────────────────────────────────────────────────────────────────┐
     │      Concern       │                            Solution                            │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Data at rest       │ AES-256-GCM, PBKDF2 key derivation, key in RAM only            │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Remote access      │ Tailscale (primary), Tor .onion (Phase 9 fallback)             │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Emergency lockdown │ Dead man's switch: ping timer → encrypt all → shutdown         │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Payload encryption │ /security/encrypter.py CLI + API                               │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Auth               │ Face ID → JWT (1hr + refresh token)                            │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Audit              │ Encrypted append-only audit log                                │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Recovery           │ Daily encrypted snapshot → integrity verify → 30-day retention │
     ├────────────────────┼────────────────────────────────────────────────────────────────┤
     │ Physical           │ Hardware kill switch for cameras + mics                        │
     └────────────────────┴────────────────────────────────────────────────────────────────┘

     ---
     Final File Structure

     /Users/parvpasricha/Desktop/myai/
     ├── server/
     │   ├── main.py                        # FastAPI root
     │   ├── llm_router.py                  # Tiered LLM routing
     │   ├── config.py                      # All env/config
     │   ├── auth.py                        # JWT issue + verify
     │   └── routes/
     │       ├── ai.py                      # Chat + context
     │       ├── security.py                # Ping, timer, lock status
     │       ├── research.py                # Topic, quiz
     │       ├── speech.py                  # Speech reports
     │       ├── dashboard.py               # WhatsParvDoing WebSocket
     │       └── friends.py                 # Friend token issuance
     ├── intelligence/
     │   ├── brain_state.py                 # Single source of truth
     │   ├── authority_rules.py             # What AI can/cannot do
     │   ├── behavior.py                    # Habit/emotion pattern analysis
     │   ├── speech_analyzer.py             # Filler words, vocab, pace
     │   ├── conversation_logger.py         # Person + topic memory
     │   ├── intent_extractor.py            # Structured intent from any input
     │   ├── correction_handler.py          # Correction detection + lesson learning
     │   └── intent_recall.py              # Natural language → memory query
     ├── security/
     │   ├── crypto.py                      # AES-256-GCM + PBKDF2
     │   ├── encrypter.py                   # Payload encrypter CLI/API
     │   ├── deadman.py                     # Ping tracker + lockdown
     │   └── audit.py                       # Encrypted audit log
     ├── recovery/
     │   ├── snapshot.py                    # Versioned archive creation
     │   ├── verify.py                      # Checksum + corruption detection
     │   ├── restore.py                     # Decrypt + restore + verify
     │   └── backup_scheduler.py            # 3am cron + weekly restore test
     ├── observability/
     │   ├── metrics.py                     # Prometheus metric definitions
     │   ├── logger.py                      # Structured JSON logger
     │   ├── healthcheck.py                 # Aggregate /health endpoint
     │   └── alerts.py                      # Alert evaluator + APNS push
     ├── memory/
     │   ├── working.py                     # Redis layer
     │   ├── episodic.py                    # SQLite + FTS5
     │   ├── semantic.py                    # ChromaDB embeddings
     │   ├── structured.py                  # PostgreSQL habits/items/emotions
     │   ├── distill.py                     # Nightly distillation cron
     │   └── context_builder.py             # Multi-layer context assembly
     ├── vision/
     │   ├── camera_pipeline.py             # RTSP → InsightFace → YOLO
     │   ├── emotion_tracker.py             # FER + MQTT + PostgreSQL
     │   └── item_tracker.py                # Zone mapping + item memory
     ├── brainwave/
     │   ├── stream.py                      # BrainFlow device connect + raw stream
     │   ├── processor.py                   # FFT band power, focus/stress indices
     │   ├── classifier.py                  # Personal scikit-learn model
     │   └── calibration.py                 # Guided calibration + baseline
     ├── research/
     │   ├── topic_generator.py             # Daily topic selection
     │   └── quiz_engine.py                 # Question gen + scoring
     ├── dashboard/
     │   └── frontend/                      # Next.js 15 app
     └── ios/
         └── ParvAI/
             ├── Services/
             │   ├── AudioService.swift     # WhisperKit STT, push-to-talk
             │   ├── ConnectionManager.swift# Tailscale/Tor, WebSocket, JWT
             │   └── PingService.swift      # Heartbeat timer
             └── Views/
                 ├── HomeView.swift
                 ├── ChatView.swift
                 ├── ResearchView.swift
                 └── StatusView.swift

     ---
     Verification Checklist (End-to-End)

     Phase 0
     - curl localhost:8000/health → ok
     - iPhone on hotspot → Tailscale connection → AI response
     - MQTT broker accepts publish/subscribe

     Phase 1
     - Grafana shows LLM latency histogram
     - Kill Redis → alert push notification < 60s
     - /health shows per-subsystem status

     Phase 2
     - Encrypt DB → restart → unreadable → password → decrypts
     - Stop ping → timer expires → lockdown → push notification
     - Run restore from yesterday's snapshot → data intact

     Phase 3
     - Push-to-talk transcribes locally < 1s
     - AI proposal push → Approve/Dismiss tap → action taken or cancelled
     - Ping heartbeat active, status widget shows countdown
     - Voice input → intent extracted → AI echoes understanding → user confirms/corrects
     - Correction recorded → lesson stored → future extraction avoids same mistake

     Phase 4
     - 6am cron → topic in app
     - 10pm quiz → scored → saved → streak updated

     Phase 5
     - Ask about yesterday's conversation → recalled correctly
     - "Where are my keys?" → correct zone + timestamp

     Phase 6
     - Weekly speech report shows filler word metrics

     Phase 7
     - Camera detects face < 2s → MQTT event fires
     - 3+ days data → behavior suggestion generated

     Phase 8
     - WhatsParvDoing updates in real time for friend viewing via friend token

     Phase 9
     - .onion address accessible via Orbot on iPhone

     Phase 10 (Pi Migration)
     - Each service migrates one at a time with laptop fallback live
     - Vision pipeline at 30+ FPS on Hailo HAT+
     - iPhone seamlessly communicates with Pi brain
     - LLM responds from Pi at 15+ tok/s for simple queries
     
      Phase 11: Smart Glasses (Very Late)

 Hardware: XIAO ESP32-S3 Sense (built-in camera + mic + BLE). Reference: OpenGlass (BasedHardware, open source).

 Features:
 - BLE → iPhone: frames forwarded to laptop for InsightFace recognition
 - Recognized person → name + last conversation date + topic → whispered via bone conduction speaker
 - Bypasses all iOS mic restrictions — hardware BLE data, not iOS microphone API

 Why very late: Hardware prototyping, BLE latency tuning, and face recognition feedback loop all have independent debugging cycles. Only makes sense after the software brain is fully stable.

     Phase 12 (Brainwave)
     - BrainFlow connects to Muse S, streams 250Hz EEG data
     - Band power values measurably different between eyes-open and eyes-closed
     - Focus index rises during coding vs. passive video watching
     - Brain State updated with brainwave field within 2s of change
     - Mood fusion returns combined estimate from brainwave + camera + speech
     - After 2 weeks: personal classifier accuracy > 75%

