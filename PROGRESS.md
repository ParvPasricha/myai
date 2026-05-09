# PARV-AI — Build Progress

**System:** Personal Autonomous Reality Vision AI  
**Hardware:** MacBook (dev) → Windows laptop i7-9th / GTX 1650 / 32GB RAM (deploy) → Pi 5 (future)  
**Started:** 2026-05-05  
**Stack:** Python 3.14 · FastAPI · Ollama · SwiftUI · SQLite → PostgreSQL · Redis · MQTT · Prometheus · Grafana

---

## Phase 0 — Core Infrastructure ✅
**Completed:** 2026-05-05

### What was built
- FastAPI server (`server/main.py`) — single hub for all subsystems
- Tiered LLM router (`server/llm_router.py`) — Ollama → Claude API → OpenAI, auto-selected by availability
- JWT auth (`server/auth.py`) — Bearer tokens, 1hr expiry + refresh
- Brain State (`intelligence/brain_state.py`) — Redis-backed single source of truth with in-process dict fallback
- Authority Rules (`intelligence/authority_rules.py`) — whitelist of what AI may act on vs. must propose
- Mosquitto MQTT broker — event bus for all subsystems
- Tailscale — secure tunnel for iPhone ↔ laptop

### Files
```
server/main.py          server/auth.py          server/config.py
server/llm_router.py    intelligence/brain_state.py
intelligence/authority_rules.py
```

### Endpoints
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /health | No | Server + MQTT status |
| POST | /auth/token | No | Issue dev JWT |
| POST | /ai/chat | Yes | LLM chat with tiered routing |
| GET | /ai/status | Yes | Ollama availability |
| GET | /brain/state | Yes | Current Brain State |
| PATCH | /brain/state | Yes | Update Brain State fields |

### Verified
- `/health` → `{"status":"ok","mqtt":true}`
- JWT issued, protected routes reject unauthenticated requests
- MQTT pub/sub round-trip confirmed
- Brain State read/write with Redis fallback
- Ollama llama3.2:3b installed and serving on Mac (dev)

---

## Phase 1 — Observability ✅
**Completed:** 2026-05-05

### What was built
- Structured JSON logger (`observability/logger.py`) — every event as `{ts, level, event, ...fields}` to `logs/parv_ai.jsonl`
- Prometheus metrics (`observability/metrics.py`) — LLM latency histograms, HTTP counters, MQTT gauge, Brain State gauges, alert counter
- Aggregate health checker (`observability/healthcheck.py`) — per-subsystem async checks (Redis, Ollama, MQTT, Brain State, PostgreSQL)
- Alert evaluator (`observability/alerts.py`) — background loop every 30s, 5-min cooldown, fires on: Redis down, Ollama down, MQTT disconnect, LLM latency > 5s, deadman < 20%
- Prometheus + Grafana installed via brew, configured to scrape `/metrics`
- Request instrumentation middleware — every HTTP request logged + measured

### Files
```
observability/logger.py     observability/metrics.py
observability/healthcheck.py    observability/alerts.py
prometheus.yml
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /metrics | No | Prometheus scrape endpoint |
| GET | /health | No | Full per-subsystem health (upgraded) |

### Verified
- Grafana at http://localhost:3000 (admin/admin)
- Prometheus at http://localhost:9090, target `parv_ai` health: `up`
- `parv_mqtt_connected = 1` queryable in Prometheus
- Redis/Ollama down → alert fires within 30s, logged to JSONL
- All `parv_*` metrics present in `/metrics` output

### Start commands
```bash
brew services start mosquitto
brew services start grafana
prometheus --config.file=prometheus.yml --storage.tsdb.path=/tmp/parv-ai-prometheus &
./start.sh
```

---

## Phase 2 — Security + Recovery ✅
**Completed:** 2026-05-05

### What was built
- **Crypto vault** (`security/crypto.py`) — PBKDF2-SHA256 (100k iterations) → 256-bit AES-256-GCM key, RAM-only, never written to disk. `encrypt_file` / `decrypt_file` / `encrypt_bytes` / `decrypt_bytes`.
- **Audit log** (`security/audit.py`) — per-entry AES-256-GCM encrypted JSONL, append-only. Falls back to plaintext with `_unencrypted` flag during lockdown.
- **Dead man's switch** (`security/deadman.py`) — RAM-only ping timestamp. Background asyncio loop checks every 10s. Configurable threshold (1min–24h). Lockdown sequence: publish MQTT event → encrypt all data → wipe key from RAM → stop services → push notification.
- **Payload encrypter** (`security/encrypter.py`) — CLI (`python -m security.encrypter encrypt file`) + API endpoints. Base64-encodes encrypted blobs for JSON transport.
- **Recovery system** (`recovery/`) — daily encrypted snapshots (`snapshot.py`), SHA-256 checksum verification (`verify.py`), decrypt+extract+post-verify restore (`restore.py`), 3am cron + Sunday dry-run test (`backup_scheduler.py`). 30-day retention.

### Files
```
security/crypto.py      security/audit.py
security/deadman.py     security/encrypter.py
recovery/snapshot.py    recovery/verify.py
recovery/restore.py     recovery/backup_scheduler.py
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /security/unlock | No | Submit master password, arm deadman |
| POST | /security/ping | Yes | Heartbeat from iPhone |
| GET | /security/status | Yes | Deadman countdown, lock state, vault state |
| PATCH | /security/timer | Yes | Update threshold minutes |
| GET | /security/audit | Yes | Read decrypted audit log (last 100) |
| POST | /security/encrypt | Yes | Encrypt arbitrary payload |
| POST | /security/decrypt | Yes | Decrypt payload |
| POST | /recovery/snapshot | Yes | Trigger manual snapshot |
| GET | /recovery/snapshots | Yes | List all snapshots |
| POST | /recovery/restore | Yes | Restore from named snapshot (dry_run supported) |

### Verified
- Vault unlock → key derived → deadman armed in RAM
- Payload encrypt → opaque blob → decrypt → original bytes recovered
- Manual snapshot created, dry-run restore: 3 files checked, all SHA-256 matched
- Audit log: 6 encrypted entries, all decrypted correctly
- Deadman threshold update → ping → next deadline updated

### Security notes
- `.salt` file must be preserved — losing it means the derived key changes
- Snapshots encrypted with current master key — must be decryptable after key re-derivation
- Lockdown is irreversible until server restarts with master password

---

## Phase 3 — iPhone App (Basic) ✅
**Completed:** 2026-05-05

### What was built
- Full SwiftUI iOS app targeting iOS 17+
- **FaceIDAuth.swift** — `LocalAuthentication` biometric gate → JWT from server → Keychain storage
- **ConnectionManager.swift** — JWT-authenticated HTTP (GET/POST/PATCH), URLSessionWebSocketTask for server push, Keychain JWT storage, Tailscale hostname config
- **AudioService.swift** — `AVAudioEngine` + `SFSpeechRecognizer` push-to-talk (on-device, no audio leaves device). WhisperKit upgrade path documented inline for Phase 6.
- **PingService.swift** — configurable interval timer, sends `/security/ping`, tracks countdown, updates `nextDeadline`
- **HomeView** — Brain State ring gauges (focus/energy/stress), activity card, ping countdown bar
- **ChatView** — hold-to-talk mic button, message bubbles (user/assistant), AI suggestion push display
- **ResearchView** — today's topic card, MCQ quiz with tab swipe, animated score reveal (added in Phase 4)
- **StatusView** — per-subsystem health rows, deadman progress bar, connection state
- **SettingsView** — server URL, ping interval stepper, mic stage picker (4 stages)
- **ParvAIApp** — Face ID login gate, 5-tab navigation

### Files
```
ios/ParvAI/App/ParvAIApp.swift
ios/ParvAI/Auth/FaceIDAuth.swift
ios/ParvAI/Services/ConnectionManager.swift
ios/ParvAI/Services/AudioService.swift
ios/ParvAI/Services/PingService.swift
ios/ParvAI/Models/BrainState.swift
ios/ParvAI/Models/AppConfig.swift
ios/ParvAI/Models/ChatMessage.swift
ios/ParvAI/Views/HomeView.swift
ios/ParvAI/Views/ChatView.swift
ios/ParvAI/Views/StatusView.swift
ios/ParvAI/Views/SettingsView.swift
ios/project.yml         (xcodegen spec, WhisperKit SPM dep)
```

### Verified
- `swiftc -typecheck` → **0 errors, 0 warnings** across all 13 Swift files
- Xcode project generated via xcodegen 2.45.4
- WhisperKit 0.18.0 resolved as SPM dependency

### To run on device
1. Open `ios/ParvAI.xcodeproj` in Xcode
2. Set Team ID in Signing & Capabilities
3. Set server URL in Settings tab to your Tailscale hostname
4. Run `./start.sh` on Mac to start backend
5. Build & run on iPhone

### Mic stage progression (user-controlled in Settings)
| Stage | Mode | When to unlock |
|-------|------|----------------|
| 1 | Push-to-talk | Active now |
| 2 | Wake phrase | After STT is stable |
| 3 | Passive context (set hours) | After habit is formed |
| 4 | VoIP always-on | Requires $99 Apple Dev account + sideload |

---

## Phase 4 — Research + Quiz Loop ✅
**Completed:** 2026-05-05

### What was built
- **SQLite database** (`research/db.py`) — tables: `user_domains`, `topics`, `research_log`, `quiz_sessions`. Seeded with 9 default interest domains. Streak calculator, weak-area query, leaderboard query.
- **Topic generator** (`research/topic_generator.py`) — LLM selects today's topic using: weak areas (score < 60) → uncovered domains → random pick. Avoids last 14 days of topics. Persists to SQLite.
- **Quiz engine** (`research/quiz_engine.py`) — generates 10 MCQ questions in 2 batches of 5 (small model compatible). Binary scoring (correct/incorrect), grade A–F, per-question explanation. Correct answers never sent to client.
- **Research scheduler** (`research/scheduler.py`) — asyncio cron: 6am topic push, 8pm reminder, 10pm quiz generation. Publishes to MQTT.
- **10 REST endpoints** (`server/routes/research.py`) — full CRUD for topics, research log, quiz, domains, leaderboard.
- **ResearchView.swift** — 3-phase UI: topic card → swipeable MCQ quiz → animated score reveal with streak ring + breakdown accordion.

### Files
```
research/db.py              research/topic_generator.py
research/quiz_engine.py     research/scheduler.py
server/routes/research.py
ios/ParvAI/Views/ResearchView.swift
memory/research.db          (SQLite, auto-created)
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /research/today | Yes | Today's topic (generates if missing) |
| POST | /research/topic/refresh | Yes | Force-regenerate today's topic |
| POST | /research/log | Yes | Log a research entry |
| GET | /research/log/{date} | Yes | Get log for a date |
| GET | /research/quiz | Yes | Get today's quiz (generates if missing) |
| POST | /research/quiz/{id} | Yes | Submit answers → score |
| GET | /research/leaderboard | Yes | Recent scores + streak |
| GET | /research/domains | Yes | List interest domains |
| POST | /research/domains | Yes | Add a domain |
| DELETE | /research/domains/{d} | Yes | Remove a domain |
| POST | /research/topic/refresh | Yes | Force regenerate |

### Verified (live run)
- Topic generated: *"Attention Mechanisms in Transformers for NLP"* — Ollama tier 1, ~24s
- Research entry logged
- 10 questions generated in 2 batches (~17s total)
- Answers submitted: score 10% / Grade F / streak 1 day
- Leaderboard shows entry, streak counted correctly
- MQTT publishes `parv/quiz/completed` on submission
- Cron scheduler running: quiz reminder fires at 8pm, quiz at 10pm

### Quiz flow
```
6:00 AM → topic generated + MQTT push
  ↓ user researches all day
8:00 PM → reminder notification
10:00 PM → quiz generated + pushed to iPhone
  ↓ user answers MCQ
         → score 0-100 + grade + streak + breakdown
  ↓ next morning topic avoids high-scored areas, revisits weak ones
```

### Notes
- `llama3.2:3b` (Mac dev) generates in ~17s for quiz, ~24s for topic — acceptable
- `llama3.2:7b-instruct-q4_K_M` on Windows GTX 1650 will be ~3x faster and higher quality
- Quiz batched into 2×5 questions because small models struggle to generate 10 valid JSON entries in one call
- Correct answers stored server-side only — client never receives them until after submission

---

## Current System State

### Services running
| Service | Port | Started by |
|---------|------|-----------|
| FastAPI (PARV-AI) | 8000 | `./start.sh` |
| Mosquitto MQTT | 1883 | brew services |
| Prometheus | 9090 | `./start.sh` |
| Grafana | 3000 | brew services |
| Ollama | 11434 | brew services |

### Completed background tasks (inside FastAPI)
| Task | Interval | Purpose |
|------|----------|---------|
| Alert loop | 30s | Redis/Ollama/MQTT/latency checks |
| Deadman loop | 10s | Ping expiry check |
| Backup scheduler | Daily 3am | Encrypted snapshots |
| Research scheduler | 6am/8pm/10pm | Topic + quiz lifecycle |

### Brain State fields (active)
```json
{
  "focus": 0–10, "energy": 0–10, "stress": 0–10,
  "deep_work": bool, "social_mode": bool,
  "learning_mode": null | string,
  "security_state": "armed" | "locked",
  "current_activity": string,
  "location": string,
  "mic_stage": "push_to_talk" | "wake_phrase" | "passive" | "voip",
  "brainwave": null   ← populated in Phase 12
}
```

---

---

## Phase 5 — Memory System (4-Layer) ✅
**Completed:** 2026-05-05

### What was built
- **Redis (Layer 1 — Working memory)** (`memory/working.py`) — last 20 messages per session, 24h TTL. `new_session()`, `append_message()`, `get_context_block()`. Falls back to in-process dict when Redis is unavailable.
- **SQLite + FTS5 (Layer 2 — Episodic memory)** (`memory/episodic.py`) — every conversation turn logged permanently. Full-text search via FTS5 virtual table. Events log. Auto-migrating schema on import.
- **ChromaDB (Layer 3 — Semantic memory)** (`memory/semantic.py`) — vector embeddings using `all-MiniLM-L6-v2` (384-dim, 90MB). Collections: `parv_summaries`, `parv_facts`, `parv_lessons`. `search_all()` queries all 3 collections ranked by cosine distance.
- **SQLite (Layer 4 — Structured memory)** (`memory/structured.py`) — typed tables: `habits`, `item_sightings`, `emotion_log`, `decisions`, `goals`, `brain_state_history`. PostgreSQL-compatible schema for Pi migration.
- **Context builder** (`memory/context_builder.py`) — assembles up to 2000-char context block from all 4 layers, injected as system prompt prefix into every LLM call.
- **Nightly distillation** (`memory/distill.py`) — 2am cron: summarises sessions via LLM → ChromaDB, extracts facts (decisions/goals/habits/items/preferences) → structured DB, snapshots Brain State, clears Redis.
- **Memory API** (`server/routes/memory_routes.py`) — 9 REST endpoints for search, recall, stats, goals, facts, item lookup, manual distillation trigger.
- **`/ai/chat` upgraded** — now logs every turn to episodic + working memory, builds personalised system prompt via context builder before each LLM call.

### Files
```
memory/working.py           memory/episodic.py
memory/semantic.py          memory/structured.py
memory/context_builder.py   memory/distill.py
server/routes/memory_routes.py
memory/episodic.db          memory/structured.db
memory/chromadb/            (ChromaDB persistence directory)
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /memory/search?q=... | Yes | Semantic search across summaries/facts/lessons |
| GET | /memory/recall?q=... | Yes | Natural language lookup (item + episodic + semantic) |
| GET | /memory/stats | Yes | Counts per collection + DB sizes |
| POST | /memory/distill | Yes | Trigger manual distillation |
| POST | /memory/fact | Yes | Manually add a semantic fact |
| POST | /memory/goal | Yes | Add a long-term goal |
| GET | /memory/goals | Yes | List active goals |
| GET | /memory/item?q=... | Yes | Find last known location of an item |
| GET | /memory/brain_history | Yes | Brain State snapshots last 24h |

### Verified (live run)
- Chat turn 1: "My name is Parv. I prefer working out before lunch." → AI confirmed understanding
- Chat turn 2 (same session): "What do you know about me?" → AI recalled name + workout preference from working memory
- `POST /memory/fact` → stored in ChromaDB `parv_facts`
- `GET /memory/item?q=keys` → `zone=desk, last_seen=0.0h ago`
- `POST /memory/distill` → 1 summary embedded in ChromaDB, 2 facts extracted
- Stats after distillation: `parv_summaries: 1, parv_facts: 2, active_goals: 1`
- Distillation scheduler running (fires at 2am daily)

### Context injection (every LLM call)
```
[CURRENT STATE] Focus:5/10 Energy:5/10 Stress:3/10 Activity:idle

[RECENT CONVERSATION]
USER: My name is Parv...
ASSISTANT: Parv! I have your preferred schedule...

[RELEVANT MEMORIES]
- Parv prefers working out before lunch

[YOUR GOALS]
- Read 2 books per month
```

### Architecture note
Layer 4 uses SQLite now with a PostgreSQL-compatible schema. In Phase 10 (Pi migration), replace `sqlite3.connect(_DB_PATH)` with `psycopg2.connect(DATABASE_URL)` — no schema changes required.

---

---

---

---

## Phase 9 — Tor Hidden Service ✅
**Completed:** 2026-05-06

### What was built
- **Tor daemon configured** — `brew install tor` + custom `torrc` at `.tor/torrc`. Hidden service dir at `.tor/hidden_service/`. Exposes:
  - `.onion:80` → `localhost:8000` (FastAPI API)
  - `.onion:3000` → `localhost:3000` (Next.js dashboard)
- **Persistent .onion address** — `hg65p5m6ux2nvpxknhzknrps2qkdtynztibncbfp52cj4uxeo2seooid.onion` (generated once, stable across restarts as long as `.tor/hidden_service/` is preserved)
- **Tor Manager** (`security/tor_manager.py`) — start/stop Tor process, read onion hostname, return status with full URL set. Designed to drop-in swap the binary path for Windows production.
- **4 new API endpoints** added to `server/routes/security.py`:
  - `POST /security/tor/start` — starts Tor, returns onion address
  - `POST /security/tor/stop` — stops process
  - `GET /security/tor/status` — running state + onion + SOCKS proxy port
  - `GET /security/onion` — quick onion URL fetch for iPhone config + iOS setup instructions
- **iOS updates:**
  - `AppConfig.swift` — `onionAddress` field persisted in UserDefaults. `onionAPIURL` computed property.
  - `ConnectionManager.swift` — `ConnectionPath` enum (LAN/Tailscale/Tor). `resolveBaseURL()` tries primary URL first, falls back to `.onion` if unreachable. `fetchAndSaveOnionAddress()` hits `/security/onion` and auto-saves.
  - `SettingsView.swift` — `.onion` field + "Fetch .onion from server" button
  - `StatusView.swift` — shows active connection path + `.onion` address

### Files
```
.tor/torrc                      — Tor configuration
.tor/hidden_service/hostname    — generated .onion address (DO NOT DELETE)
.tor/hidden_service/private_key — hidden service private key (DO NOT EXPOSE)
security/tor_manager.py
server/routes/security.py      — 4 new Tor endpoints appended
ios/ParvAI/Models/AppConfig.swift   — onionAddress field
ios/ParvAI/Services/ConnectionManager.swift — Tor path + fetch method
ios/ParvAI/Views/SettingsView.swift — onion config UI
ios/ParvAI/Views/StatusView.swift   — active path display
```

### Connection priority (iOS)
```
1. Primary URL (LAN/Tailscale) — fast, sub-10ms
2. .onion via Orbot SOCKS5    — slower (~500ms), max privacy
```
Auto-switches: if primary URL health check fails within 5s, tries `.onion`.

### Verified
- `.onion` address: `hg65p5m6ux2nvpxknhzknrps2qkdtynztibncbfp52cj4uxeo2seooid.onion`
- `GET /security/onion` → correct API URL + dashboard URL + iOS instructions ✓
- `POST /security/tor/start` → starts Tor process, returns onion in 516ms ✓
- `GET /security/tor/status` → running state + SOCKS proxy `127.0.0.1:9050` ✓
- `POST /security/tor/stop` → stops cleanly ✓
- iOS Swift typecheck: **0 errors** after all Tor additions ✓
- torsocks connectivity: Tor daemon starts, SOCKS listener on 9050. Circuit bootstraps ~60-90s after both Tor + FastAPI are running.

### To use on iPhone
1. Install **Orbot** from App Store (free Tor proxy)
2. Enable Orbot VPN mode
3. In ParvAI Settings → tap "Fetch .onion from server" (while on same network)
4. Disconnect from local network → app auto-routes via Tor

### Critical: DO NOT lose these files
- `.tor/hidden_service/hostname` — your .onion address
- `.tor/hidden_service/private_key` — losing this = new address, must reconfigure friends
- `.tor/hidden_service/` is included in nightly snapshots via `recovery/snapshot.py`

### Windows production note
Change `_TOR_BIN` in `security/tor_manager.py`:
```python
_TOR_BIN = "C:\\Tor\\tor.exe"   # Windows
```
Update `DataDirectory` and `HiddenServiceDir` paths in `.tor/torrc` to Windows-style paths.

---

## Phase 8 — WhatsParvDoing Dashboard ✅
**Completed:** 2026-05-06

### What was built
- **Dashboard backend** (`server/routes/dashboard.py`) — public `GET /dashboard/public` endpoint (no auth required — safe public data only). `POST /dashboard/location` and `POST /dashboard/activity` for iPhone to push updates. `GET /dashboard/ws/status` for monitoring. `broadcast_state()` hooked into Brain State PATCH — every Brain State update instantly fans out to all connected WebSocket clients.
- **WebSocket server** (`/ws/dashboard`) — `asyncio` connection manager with reconnect-safe pub/sub. Sends current state snapshot on connect, then pushes all Brain State changes live. Keepalive ping/pong. Auto-cleans dead connections.
- **Friend tokens** (`server/routes/friends.py`) — signed JWTs with `scope="friend"`. `POST /friends/token` issues a shareable URL. `DELETE /friends/{name}` revokes instantly. Tokens stored in `memory/friend_tokens.json`. Friends get a URL like `http://yourserver:3000/?token=<jwt>`.
- **Next.js 15 frontend** (`dashboard/frontend/`) — TypeScript, Tailwind CSS, App Router. Dark-themed dashboard (`bg-zinc-950`). `useDashboard` hook connects WebSocket and falls back to REST polling. Auto-reconnects every 3s if connection drops.
- **Components:** `BrainStateCard` (animated SVG ring gauges for focus/energy/stress), `ActivityCard` (current activity + location + mic stage), `TopicCard` (today's research + quiz status badge), `ConnectionDot` (pulsing green live indicator), `EmotionBadge` (emoji + emotion label).

### Files
```
server/routes/dashboard.py      server/routes/friends.py
dashboard/frontend/src/
  app/page.tsx                  — main page with Suspense boundary
  lib/useDashboard.ts           — WebSocket hook + REST fallback
  components/BrainStateCard.tsx
  components/ActivityCard.tsx
  components/TopicCard.tsx
  components/ConnectionDot.tsx
  components/EmotionBadge.tsx
  .env.local                    — NEXT_PUBLIC_API_URL=http://localhost:8000
memory/friend_tokens.json       (auto-created)
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /dashboard/public | None | Current dashboard payload (safe) |
| WS | /ws/dashboard | None | Real-time Brain State stream |
| POST | /dashboard/location | JWT | iPhone location push |
| POST | /dashboard/activity | JWT | Manual activity update |
| GET | /dashboard/history | JWT | 24h Brain State history |
| GET | /dashboard/ws/status | JWT | Connected WebSocket client count |
| POST | /friends/token | JWT | Issue friend link |
| GET | /friends | JWT | List friends |
| DELETE | /friends/{name} | JWT | Revoke friend access |

### Dashboard payload (public — no secrets)
```json
{
  "current_activity": "coding",
  "focus_score": 8,
  "energy_score": 6,
  "stress_score": 3,
  "deep_work": true,
  "location": "home/desk",
  "emotion": "focused",
  "today_topic": "Attention Mechanisms in Transformers",
  "quiz_status": "pending",
  "last_updated": "2026-05-06T01:43:00Z"
}
```

### Verified (live run)
- `GET /dashboard/public` → correct activity/location before and after updates ✓
- `POST /dashboard/location {location: "home/desk"}` → reflected immediately in public endpoint ✓
- Friend token issued for Rohan → URL `http://localhost:3000/?token=eyJ...` ✓
- Friend accesses `GET /dashboard/public?token=<jwt>` → sees same public data ✓
- Revoke friend → `GET /friends` shows empty list ✓
- Next.js 15 `npm run build` → compiled successfully, 0 TypeScript errors ✓

### To start the dashboard
```bash
# Terminal 1: API backend
./start.sh

# Terminal 2: Next.js frontend
cd dashboard/frontend && npm run dev
# Open http://localhost:3000
```

### For friends
```bash
# Issue a token (server must be running)
curl -s -X POST http://localhost:8000/friends/token \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Rohan", "expires_days": 30}'
# Returns dashboard_url → share with friend
```

---

## Phase 6 — Speech Improvement AI ✅
**Completed:** 2026-05-06

### What was built
- **Speech Analyzer** (`intelligence/speech_analyzer.py`) — per-transcript metrics: filler word count+rate (um/uh/like/basically/you know/etc.), vocabulary richness (type-token ratio), rare word ratio, avg sentence length, WPM (if duration given), TextBlob sentiment, composite complexity score 0–10. Stores every session in `memory/speech.db`. Weekly aggregation with previous-week delta comparison.
- **Conversation Logger** (`intelligence/conversation_logger.py`) — NLTK POS-tag NNP detection extracts person names from transcripts. Logs `{name, topic, sentiment, date, snippet}` to `memory/conversations.db`. Powers "when did I last talk to X?" queries with human-readable responses. Topic extracted via noun-frequency heuristic (no LLM needed).
- **Speech routes** (`server/routes/speech.py`) — 8 REST endpoints. `POST /speech/analyze` returns metrics + people detected + actionable tip. Weekly report compares this week vs last. `GET /speech/last/{name}` → natural language response.
- **Auto-analysis in `/ai/chat`** — every user message ≥5 words is background-analyzed for speech metrics + people. Zero latency impact (asyncio background task).

### Files
```
intelligence/speech_analyzer.py
intelligence/conversation_logger.py
server/routes/speech.py
memory/speech.db          (auto-created)
memory/conversations.db   (auto-created)
```

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /speech/analyze | Yes | Analyze transcript → metrics + tip + people |
| GET | /speech/report | Yes | Weekly report + previous week comparison |
| GET | /speech/report/previous | Yes | Last week's metrics |
| GET | /speech/sessions | Yes | Recent session list (no transcript) |
| GET | /speech/people | Yes | All known people + this week's interactions |
| GET | /speech/person/{name} | Yes | Full history for a person |
| GET | /speech/last/{name} | Yes | "Last talked to X N days ago about Y" |

### Verified (live run)
**Filler-heavy transcript** (46 words, "So um I was like basically..."):
- Filler count: 10 | Rate: 21.7/100 words
- Fillers detected: `['like', 'basically', 'um', 'so', 'i mean', 'you know']`
- Complexity: 4.67/10
- Tip: *"High filler rate (21.7/100 words). Most used: 'like'. Try pausing silently instead."*
- People detected: `['Rohan', 'Priya']`

**Clean technical transcript** (29 words, "The transformer architecture..."):
- Filler rate: 0.0/100 | WPM: 116 | Complexity: 10/10
- Tip: *"Strong speech! Complexity score 10.0/10. Keep it up."*

**Person recall:** `GET /speech/last/Rohan` → *"Last talked to Rohan today, about: concept, thing, start."*

**Weekly report:** 2 sessions, avg filler rate 10.87/100, top filler: 'like'

### Tip generation logic
| Condition | Tip shown |
|-----------|-----------|
| Filler rate > 5/100 | Names worst filler word, suggests silent pause |
| Vocab richness < 0.4 | Suggests varying word choice |
| WPM > 180 | Slowing down recommendation |
| WPM < 100 | Be more concise |
| Complexity > 7 | Positive reinforcement |

### Mic stage note
Speech analyzer works on any text input — push-to-talk transcripts (Stage 1, active), voice transcripts from future mic stages (2–4), or manual input. No dependency on mic stage.

---

---

## Phase 7 — Vision Pipeline ✅
**Completed:** 2026-05-06

### What was built
- **Zone Mapper** (`vision/zone_mapper.py`) — polygon-based room zones (desk, shelf, floor, etc.) stored in `memory/zones.json` per camera_id. Point-in-polygon ray-casting. `bbox_zone()` maps object bottom-centre to zone. Default 4-quadrant zones auto-created when unset.
- **Face Recognition** (`vision/face_recognition.py`) — OpenCV Haar cascade detection + LBPH recognizer for identity matching. Enrolls known faces via uploaded photos (store multiple angles for accuracy). Confidence threshold 80. Logs every recognition to `memory/faces.db`. On Windows GPU: swap `_classify_emotion_heuristic()` with InsightFace/ArcFace ONNX — no other changes needed.
- **Emotion Tracker** (`vision/emotion_tracker.py`) — heuristic emotion classification from facial pixel patterns (brightness→tired, edge density→happy, contrast→surprised). On Windows: plug in FER+ ONNX via `onnxruntime`. Logs to `memory/structured.py` emotion_log. Updates Brain State (`stress`/`energy`) on emotion change. Publishes `parv/emotion/detected` to MQTT.
- **Item Tracker** (`vision/item_tracker.py`) — YOLOv11n (ultralytics, 80 COCO classes) with a 40-class household item filter. Maps detections to zones via `bbox_zone()`. Upserts `memory/structured.py` item_sightings. Publishes `parv/item/seen` to MQTT. Processes every 5th frame (CPU efficiency — configurable).
- **Camera Pipeline** (`vision/camera_pipeline.py`) — async orchestrator: webcam (dev) or RTSP URL (production). Runs face→emotion→item pipeline per frame at configurable FPS. Start/stop via API. Single-frame processing for API uploads.
- **Behavior Analyzer** (`intelligence/behavior.py`) — patterns from emotion timeline: peak focus hours, energy dip hours, stress spike count, mood score (-10 to +10). Pushes suggestions to iPhone via `parv/ai/suggestion` MQTT. Called by nightly distillation.
- **Vision API** (`server/routes/vision.py`) — 13 REST endpoints. File upload for frame analysis and face enrollment. Zone CRUD. Item queries. Emotion trend + behavior analysis.

### Files
```
vision/__init__.py              vision/zone_mapper.py
vision/face_recognition.py      vision/emotion_tracker.py
vision/item_tracker.py          vision/camera_pipeline.py
vision/known_faces/             (enrolled face images)
intelligence/behavior.py
server/routes/vision.py
memory/faces.db                 memory/zones.json
```

### Dependencies added
- `ultralytics>=8.3` — YOLOv11n object detection (CoreML on Mac, CUDA on Windows)
- `opencv-python-headless>=4.10` — camera capture, Haar cascade, LBPH face recognizer
- `onnxruntime` — ready for InsightFace/FER+ ONNX models on Windows
- `python-multipart` — FastAPI file upload support

### Endpoints added
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | /vision/start | Yes | Start pipeline (webcam or RTSP) |
| POST | /vision/stop | Yes | Stop pipeline + return stats |
| GET | /vision/status | Yes | Running state + frame count |
| POST | /vision/frame | Yes | Analyze uploaded image (multipart) |
| POST | /vision/enroll | Yes | Enroll face from uploaded image |
| GET | /vision/faces | Yes | List known enrolled identities |
| GET | /vision/recognitions | Yes | Recent recognition log |
| GET | /vision/zones | Yes | Get configured zones |
| POST | /vision/zones | Yes | Set/update zones |
| GET | /vision/items | Yes | All tracked item locations |
| GET | /vision/item/{name} | Yes | Find specific item's last zone |
| GET | /vision/emotions | Yes | Recent emotion log |
| GET | /vision/behavior | Yes | Pattern analysis + observations |

### Verified (synthetic frames, no camera)
- Zone mapper: point-in-polygon correct for all 4 default quadrant zones
- Emotion: bright face → `focused (0.6)`, dark face → `tired (0.6)`, logged to DB
- Item query: `[('laptop','desk'), ('headphones','shelf'), ('keys','desk')]`
- `GET /vision/item/headphones` → `{found: true, zone: shelf}`
- Behavior analysis: 8 data points → mood_score, distribution, peak_focus observation
- All 5 API endpoints return 200 with correct data

### Production notes (Windows GTX 1650)
| Component | Mac dev | Windows production |
|-----------|---------|-------------------|
| YOLO inference | CPU (2-3 FPS) | CUDA (15-25 FPS) |
| Face detection | Haar cascade | InsightFace ArcFace (ONNX) |
| Emotion | Heuristic | FER+ ONNX model |
| Camera source | `"webcam"` | `"rtsp://ip:554/stream"` |
| Frame rate | 1-2 FPS | 5-10 FPS |

To upgrade face recognition for Windows: replace `_classify_emotion_heuristic()` in `emotion_tracker.py` with `ort.InferenceSession("fer_plus.onnx")` and `identify_face()` in `face_recognition.py` with InsightFace ONNX embeddings.

---

---

## Code Review — 27 Issues Fixed ✅
**Completed:** 2026-05-08

Full security + quality review run across all backend files. Two review agents examined: `security/`, `server/`, `memory/`, `research/`, `intelligence/`, `vision/`, `recovery/`. All 27 findings fixed and verified.

### CRITICAL (4)
| Fix | File |
|-----|------|
| `/auth/token` now returns 404 in production (`PARV_ENV=production`) | `server/main.py` |
| JWT secret raises `RuntimeError` at startup if default/unset in production | `server/config.py` |
| `/security/unlock` rate-limited: 5 wrong attempts → 5-min lockout (HTTP 429) | `server/routes/security.py` |
| Password verification using encrypted `.verify` token — wrong password actually rejected | `security/crypto.py` |

### HIGH (13)
| Fix | File |
|-----|------|
| `lock()` zeroes `bytearray` key bytes in-place (was allocating new bytes object) | `security/crypto.py` |
| Master key wiped *before* lockdown hooks run (not after) | `security/deadman.py` |
| `remaining = threshold_seconds() - 0` → fixed to actual remaining | `security/deadman.py` |
| Friend tokens: only SHA-256 hash stored on disk, not raw JWT | `server/routes/friends.py` |
| Path traversal in restore blocked via `resolve()` + prefix guard | `server/routes/security.py` |
| Background tasks awaited on shutdown with `asyncio.gather(return_exceptions=True)` | `server/main.py` |
| Ollama health check: 30s TTL cache (was one HTTP call per LLM request) | `server/llm_router.py` |
| Distill clears Redis only for successfully processed sessions | `memory/distill.py` |
| Quiz `json.loads` wrapped — parse failure raises `RuntimeError` with context | `research/quiz_engine.py` |
| Camera pipeline start/stop guarded with `asyncio.Lock` | `vision/camera_pipeline.py` |
| WebSocket broadcast uses `list()` snapshot, calls `disconnect()` for dead sockets | `server/routes/dashboard.py` |
| Tarball restore: extract to temp dir → verify → atomic copy (no mid-write data loss) | `recovery/restore.py` |
| Tarball member names path-traversal guarded during extraction | `recovery/restore.py` |

### MEDIUM/LOW (10)
| Fix | File |
|-----|------|
| Refresh tokens rejected as access tokens (HTTP 401) | `server/auth.py` |
| CORS restricted to `localhost:3000/8000` + Tailscale hostname (no wildcard) | `server/main.py` |
| Tor stderr captured; silent start failures now surface error text | `security/tor_manager.py` |
| `.salt` file written with `0o600` permissions (was world-readable) | `security/crypto.py` |
| Blob-embedded salt validated on decrypt — salt rotation raises a clear error | `security/crypto.py` |
| `expires_days=0` now creates immediately-expiring token (was non-expiring) | `server/routes/friends.py` |
| Anthropic + OpenAI SDK clients instantiated once, reused per process | `server/llm_router.py` |
| Ollama `KeyError` on malformed response → cache invalidated + retries tier 2 | `server/llm_router.py` |
| Chat errors return HTTP 422/503 instead of `{"error": "..."}` with 200 | `server/main.py` |
| Fire-and-forget tasks tracked in `_bg_tasks` set with logged `done_callback` | `server/main.py` |
| Weekly speech report: 2 flat queries replacing 4-level recursion | `intelligence/speech_analyzer.py` |
| `encrypt_dir` uses suffix allowlist (`.db/.json/.jsonl/.pkl`) — skips `.pyc`, audit log | `security/crypto.py` |
| ItemTracker dict per camera_id — no YOLO model leak on camera change | `vision/item_tracker.py` |
| SQLite `_migrate()` connections explicitly closed at module load | `intelligence/speech_analyzer.py`, `conversation_logger.py` |
| Pipeline stats dict reset on each new camera pipeline run | `vision/camera_pipeline.py` |

### New files created by fixes
- `.verify` — AES-encrypted known-plaintext for password verification (auto-created on first unlock)

---

## Upcoming Phases

| Phase | Name | Status |
|-------|------|--------|
| 6 | Speech Improvement AI | ✅ Done |
| 7 | Vision Pipeline | ✅ Done |
| 8 | WhatsParvDoing Dashboard | ✅ Done |
| 9 | Tor Hidden Service | ✅ Done |
| Code Review | 27 issues fixed | ✅ Done |
| 10 | Pi Migration | 🔄 Hardware pending |
| 11 | Smart Glasses | Hardware pending |
| 12 | Brainwave Scanner | Hardware pending |
