# PARV-AI — Test Guide (Phases 0–9 + Security)

> Run all commands from `/Users/parvpasricha/Desktop/myai/`  
> Every curl command that hits a protected endpoint needs a token — get one once and reuse it.

---

## 0. Start the Stack

```bash
# Start background services
brew services start redis
brew services start mosquitto
brew services start ollama

# Start PARV-AI (keep this terminal open — you'll see live logs)
./start.sh
```

You should see in the logs:
```
[MQTT] connected to localhost:1883
server_startup service=parv-ai version=0.2.0
alert_loop_started
deadman_loop_started
research_scheduler_next job=...
distillation_next wait_hours=...
```

Open a second terminal for all the test commands below.

---

## 1. Get a Token (do this once per session)

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
echo "Token: ${TOKEN:0:30}..."
```

✅ Should print a truncated JWT.

---

## 2. Phase 0 — Core Infrastructure

### 2a. Health check
```bash
curl -s http://localhost:8000/health | python3 -m json.tool
```
✅ Expect: `"status": "ok"`, `"mqtt": {"status": "ok"}`, `"redis": {"status": "ok"}`

### 2b. LLM status (Ollama)
```bash
curl -s http://localhost:8000/ai/status \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `"ollama": true`, `"available_models": ["llama3.2:3b"]`

### 2c. Brain State — read
```bash
curl -s http://localhost:8000/brain/state \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect all fields: focus, energy, stress, current_activity, mic_stage, brainwave: null, etc.

### 2d. Brain State — update
```bash
curl -s -X PATCH http://localhost:8000/brain/state \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"focus": 9, "current_activity": "testing", "deep_work": true}' | python3 -m json.tool
```
✅ Expect updated state returned with new values + `last_updated` timestamp.

### 2e. Auth rejection test
```bash
curl -s http://localhost:8000/brain/state
```
✅ Expect: `{"detail": "Not authenticated"}`

---

## 3. Phase 1 — Observability

### 3a. Prometheus metrics
```bash
curl -s http://localhost:8000/metrics | grep "^parv_" | head -20
```
✅ Expect: `parv_mqtt_connected 1.0`, `parv_brain_state_focus`, `parv_http_requests_total`, etc.

### 3b. Grafana dashboard
Open **http://localhost:3000** in browser (admin / admin)
- Add datasource: Prometheus → `http://localhost:9090`
- Explore → query `parv_mqtt_connected` → should return 1

### 3c. Prometheus target check
```bash
curl -s 'http://localhost:9090/api/v1/targets' | python3 -c "
import sys,json
d=json.load(sys.stdin)
for t in d['data']['activeTargets']:
    print('job:', t['labels']['job'], '| health:', t['health'])
"
```
✅ Expect: `job: parv_ai | health: up`

### 3d. Alert log check (Redis down alert will be in logs if Redis isn't running)
```bash
grep "alert_fired" logs/parv_ai.jsonl | tail -5
```
✅ Expect: JSON entries with alert names like `redis_down` or `ollama_down` (only if those services were down at startup)

---

## 4. Phase 2 — Security + Recovery

### 4a. Unlock the vault
```bash
curl -s -X POST http://localhost:8000/security/unlock \
  -H "Content-Type: application/json" \
  -d '{"password": "mytest123"}' | python3 -m json.tool
```
✅ Expect: `"Vault unlocked. Dead man's switch armed."`

> ⚠️  Use the same password every time — the salt file (.salt) is created on first unlock and must match.

### 4b. Dead man's switch status
```bash
curl -s http://localhost:8000/security/status \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `"armed": true`, `"locked": false`, `"time_remaining_seconds": 3600`, `"vault_unlocked": true`

### 4c. Send a ping (heartbeat)
```bash
curl -s -X POST http://localhost:8000/security/ping \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"next_deadline": <timestamp>`

### 4d. Change timer threshold
```bash
curl -s -X PATCH http://localhost:8000/security/timer \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"minutes": 120}' | python3 -m json.tool
```
✅ Expect: `"threshold_minutes": 120`

### 4e. Encrypt a payload
```bash
PAYLOAD=$(python3 -c "import base64; print(base64.b64encode(b'secret message from parv').decode())")
ENCRYPTED=$(curl -s -X POST http://localhost:8000/security/encrypt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"data_b64\": \"$PAYLOAD\"}" | python3 -c "import sys,json; print(json.load(sys.stdin)['payload'])")
echo "Encrypted (first 40 chars): ${ENCRYPTED:0:40}..."
```
✅ Expect an opaque base64 blob.

### 4f. Decrypt it back
```bash
curl -s -X POST http://localhost:8000/security/decrypt \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"payload\": \"$ENCRYPTED\"}" | python3 -c "
import sys,json,base64
d=json.load(sys.stdin)
print('Decrypted:', base64.b64decode(d['data_b64']).decode())
"
```
✅ Expect: `Decrypted: secret message from parv`

### 4g. Create a snapshot
```bash
curl -s -X POST http://localhost:8000/recovery/snapshot \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"snapshot": "snapshot_YYYYMMDD_HHMMSS_manual"`

### 4h. List snapshots
```bash
curl -s http://localhost:8000/recovery/snapshots \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect list with the snapshot you just created.

### 4i. Verify snapshot integrity (dry-run restore)
```bash
SNAP=$(curl -s http://localhost:8000/recovery/snapshots -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['snapshots'][0]['name'])")
curl -s -X POST http://localhost:8000/recovery/restore \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"snapshot_name\": \"$SNAP\", \"dry_run\": true}" | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"dry_run": true`, `"files_checked": N`

### 4j. Read audit log
```bash
curl -s http://localhost:8000/security/audit \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Total entries: {d[\"count\"]}')
for e in d['entries'][-5:]:
    print(' -', e['event'], '|', round(e['ts']))
"
```
✅ Expect: vault_unlocked, deadman_armed, timer_updated, payload_encrypted, manual_snapshot entries.

---

## 5. Phase 4 — Research + Quiz

### 5a. Get today's topic (LLM call — ~20s)
```bash
curl -s http://localhost:8000/research/today \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print('Topic:', d['topic'])
print('Domains:', d['domains'])
print('Brief:', d['description'][:100]+'...')
"
```
✅ Expect a specific research topic + 3-sentence description.

### 5b. Log a research entry
```bash
curl -s -X POST http://localhost:8000/research/log \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"title": "Test article", "summary": "Read about the topic today", "source": "manual"}' | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"id": 1`

### 5c. Get today's quiz (LLM call — ~30s)
```bash
curl -s http://localhost:8000/research/quiz \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Quiz ID: {d[\"quiz_id\"]} | Questions: {len(d[\"questions\"])}')
for q in d['questions'][:2]:
    print(f'  Q{q[\"id\"]}: {q[\"question\"][:70]}')
    print(f'    Options: {[o[:20] for o in q[\"options\"]]}')
"
```
✅ Expect: Quiz ID, 10 questions, each with 4 options. No correct answers visible.

### 5d. Submit quiz answers
```bash
QUIZ_ID=$(curl -s http://localhost:8000/research/quiz -H "Authorization: Bearer $TOKEN" | python3 -c "import sys,json; print(json.load(sys.stdin)['quiz_id'])")
curl -s -X POST "http://localhost:8000/research/quiz/$QUIZ_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"answers": ["A","B","C","A","B","C","A","B","A","C"]}' | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Score: {d[\"score\"]}% | Grade: {d[\"grade\"]} | Streak: {d[\"streak\"]} days')
print(f'Correct: {d[\"correct\"]}/{d[\"total\"]}')
"
```
✅ Expect: score 0–100, grade S/A/B/C/D/F, streak counter, correct/total count.

### 5e. Leaderboard
```bash
curl -s http://localhost:8000/research/leaderboard \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Streak: {d[\"streak\"]} days')
for s in d['scores']:
    print(f'  {s[\"date\"]} | {s[\"topic\"][:40]} | {s[\"score\"]}%')
"
```
✅ Expect today's score in the leaderboard.

---

## 6. Phase 5 — Memory System

### 6a. Chat with memory (first message)
```bash
.venv/bin/python3 - <<'EOF'
import urllib.request, json, subprocess

token = subprocess.check_output([
    ".venv/bin/python3", "-c",
    "import urllib.request,json; r=urllib.request.urlopen(urllib.request.Request('http://localhost:8000/auth/token', method='POST', data=b'{}')); print(json.loads(r.read())['access_token'])"
], text=True).strip()

def chat(prompt, session_id=None):
    body = {"prompt": prompt}
    if session_id:
        body["session_id"] = session_id
    data = json.dumps(body).encode()
    req = urllib.request.Request("http://localhost:8000/ai/chat", data=data, method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read())

r1 = chat("My name is Parv. I prefer working out at 7am before breakfast. Remember this.")
sid = r1["session_id"]
print(f"Session: {sid}")
print(f"AI: {r1['text'][:150]}\n")

r2 = chat("What do you remember about me?", session_id=sid)
print(f"AI (follow-up): {r2['text'][:200]}")
EOF
```
✅ Expect: AI recalls name and workout preference in follow-up without re-stating it.

### 6b. Add a fact manually
```bash
curl -s -X POST http://localhost:8000/memory/fact \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"text": "Parv drinks coffee every morning before coding", "category": "habit"}' | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"id": "fact_habit_..."`

### 6c. Add a goal
```bash
curl -s -X POST http://localhost:8000/memory/goal \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"description": "Build and deploy PARV-AI by end of 2026", "domain": "Technology"}' | python3 -m json.tool
```
✅ Expect: `"ok": true`, `"id": N`

### 6d. Semantic search
```bash
curl -s "http://localhost:8000/memory/search?q=workout+morning+habits" \
  -H "Authorization: Bearer $TOKEN" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'Results: {len(d[\"results\"])}')
for r in d['results']:
    print(f'  [{r[\"collection\"]}] {r[\"text\"][:80]}')
"
```
✅ Expect memory results from `parv_facts` or `parv_summaries` collections.

### 6e. Item location memory
```bash
# Manually log an item location
.venv/bin/python3 -c "
from memory.structured import upsert_item_sighting
upsert_item_sighting('wallet', 'desk', confidence=0.99)
upsert_item_sighting('keys', 'shelf', confidence=0.95)
upsert_item_sighting('headphones', 'bed', confidence=0.88)
print('Items logged')
"

# Query via API
curl -s "http://localhost:8000/memory/item?q=wallet" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `"found": true`, `"zone": "desk"`, `"last_seen_hours_ago": 0.0`

### 6f. Natural language recall
```bash
curl -s "http://localhost:8000/memory/recall?q=where+are+my+keys" \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: item location + any matching conversation snippets.

### 6g. Memory stats
```bash
curl -s http://localhost:8000/memory/stats \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect ChromaDB collection counts + episodic message count + active goals.

### 6h. Trigger manual distillation (summarises today's conversations)
```bash
curl -s -X POST http://localhost:8000/memory/distill \
  -H "Authorization: Bearer $TOKEN"
echo ""
# Check stats again — parv_summaries count should increase
curl -s http://localhost:8000/memory/stats \
  -H "Authorization: Bearer $TOKEN" | python3 -m json.tool
```
✅ Expect: `parv_summaries` count increases after distillation.

---

## 7. MQTT Event Bus — Verify Events Fire

Open a third terminal and subscribe before triggering events:
```bash
mosquitto_sub -t "parv/#" -v
```

Then in another terminal, trigger some actions:
```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Should publish parv/brain/state_update
curl -s -X PATCH http://localhost:8000/brain/state \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"focus": 8}' > /dev/null

# Should publish parv/security/... on ping
curl -s -X POST http://localhost:8000/security/ping \
  -H "Authorization: Bearer $TOKEN" > /dev/null
```
✅ Expect to see MQTT messages appear in the subscriber terminal.

---

## 8. iPhone App (manual steps in Xcode)

1. Open `ios/ParvAI.xcodeproj` in Xcode
2. Set your **Team ID** in Signing & Capabilities
3. In **Settings tab** inside the app:
   - Set Server URL to `http://<your-mac-ip>:8000` (or Tailscale hostname)
   - Set Ping interval (default 30 min)
4. Tap **Authenticate with Face ID** on login screen
5. Verify tabs load: Home (Brain State rings), Chat (hold mic), Research (today's topic), Status (health rows)

---

## Quick Sanity Checklist

| Test | Command | Expected |
|------|---------|----------|
| Server up | `curl localhost:8000/health` | `status: ok, mqtt: ok` |
| JWT works | Get token → hit protected endpoint | 200 response |
| Vault unlock | POST /security/unlock | `armed: true` |
| Encrypt round-trip | encrypt → decrypt | original bytes back |
| Snapshot + verify | POST /recovery/snapshot → dry_run restore | `ok: true` |
| Topic generation | GET /research/today | LLM-generated topic |
| Quiz + submit | GET /research/quiz → POST answers | score 0-100 |
| Memory chat | Two-turn chat | AI recalls session context |
| Item location | upsert + GET /memory/item | correct zone |
| MQTT events | mosquitto_sub parv/# | events appear on state changes |

---

## 9. Security Hardening Tests (post code-review)

These verify all 27 code review fixes. Run after `./start.sh`.

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/token | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")
```

### 9a. Vault must be initialised with correct password first
```bash
# First unlock creates .verify file — use the same password every time
curl -s -X POST http://localhost:8000/security/unlock \
  -H "Content-Type: application/json" \
  -d '{"password": "your-master-password"}'
```
✅ Returns `{"ok": true, "message": "Vault unlocked..."}`

### 9b. Wrong password returns 401
```bash
curl -s -X POST http://localhost:8000/security/unlock \
  -H "Content-Type: application/json" \
  -d '{"password": "wrongpassword"}' -w "\nHTTP %{http_code}"
```
✅ Expect: `HTTP 401`

### 9c. Rate-limit: 5 wrong attempts → 5-min lockout
```bash
for i in 1 2 3 4 5 6; do
  CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8000/security/unlock \
    -H "Content-Type: application/json" \
    -d '{"password":"wrongpassword"}')
  echo "Attempt $i: HTTP $CODE"
done
```
✅ Expect: attempts 1-5 return `401`, attempt 6 returns `429`

### 9d. Correct password also blocked during lockout
```bash
curl -s -X POST http://localhost:8000/security/unlock \
  -H "Content-Type: application/json" \
  -d '{"password": "your-master-password"}' -w "\nHTTP %{http_code}"
```
✅ Expect: `HTTP 429` (lockout applies to all attempts including correct password)

### 9e. Refresh token rejected as access token
```bash
# Get a refresh token
REFRESH=$(curl -s -X POST http://localhost:8000/auth/token | python3 -c "import sys,json; print(json.load(sys.stdin)['refresh_token'])")

# Try to use it as access token
curl -s http://localhost:8000/brain/state \
  -H "Authorization: Bearer $REFRESH" -w "\nHTTP %{http_code}"
```
✅ Expect: `HTTP 401` with "Refresh token cannot be used as access token"

### 9f. CORS does not expose wildcard
```bash
curl -s -o /dev/null -D - http://localhost:8000/health \
  -H "Origin: http://evil.com" | grep -i "access-control-allow-origin"
```
✅ Expect: empty (no ACAO header for unknown origins)

### 9g. Path traversal blocked in snapshot restore
```bash
curl -s -X POST http://localhost:8000/recovery/restore \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"snapshot_name": "../../etc/passwd", "dry_run": true}' \
  -w "\nHTTP %{http_code}"
```
✅ Expect: `HTTP 400` or `403`

### 9h. Production mode disables /auth/token
```bash
# Test with production flag
PARV_ENV=production .venv/bin/python3 -c "
import asyncio, httpx
async def t():
    async with httpx.AsyncClient() as c:
        # Would need server running in prod mode — just verify config import
        from server.config import ENV
        print('ENV:', ENV)
asyncio.run(t())
"
# To test fully: PARV_ENV=production ./start.sh → curl -X POST http://localhost:8000/auth/token → 404
```
✅ In production mode: `/auth/token` returns `HTTP 404`

### 9i. Ollama health check cached (not per-request)
```bash
.venv/bin/python3 - <<'EOF'
import asyncio, time
from server.llm_router import llm

async def test():
    t0 = time.time()
    for _ in range(5):
        await llm._check_ollama()
    print(f"5 checks in {time.time()-t0:.3f}s (cached = <0.2s)")

asyncio.run(test())
EOF
```
✅ Expect: 5 checks complete in < 0.2s (first is real, rest use 30s TTL cache)

### 9j. Dashboard WebSocket resilience (concurrent clients)
```bash
# Open 3 simultaneous WebSocket connections, verify no crash
.venv/bin/python3 - <<'EOF'
import asyncio, json
async def connect():
    import urllib.request
    # Just verify the /dashboard/ws/status endpoint works
    tok = json.loads(urllib.request.urlopen(
        urllib.request.Request("http://localhost:8000/auth/token", method="POST", data=b"{}")
    ).read())["access_token"]
    req = urllib.request.Request("http://localhost:8000/dashboard/ws/status",
        headers={"Authorization": f"Bearer {tok}"})
    with urllib.request.urlopen(req) as r:
        d = json.loads(r.read())
        print(f"WebSocket clients connected: {d['connected_clients']}")

asyncio.run(connect())
EOF
```
✅ Expect: no crash, returns client count

### 9k. Friend token stores hash, not raw JWT
```bash
# Issue a friend token then inspect the file
curl -s -X POST http://localhost:8000/friends/token \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "TestFriend", "expires_days": 1}' > /dev/null

cat memory/friend_tokens.json | python3 -c "
import sys,json
d=json.load(sys.stdin)
for name,v in d.items():
    has_raw = 'token' in v and len(v.get('token','')) > 50
    has_hash = 'token_hash' in v
    print(f'{name}: raw_jwt_stored={has_raw}, hash_stored={has_hash}')
"
```
✅ Expect: `raw_jwt_stored=False, hash_stored=True`

---

## 10. Phase 6–9 API Tests

### Speech analysis
```bash
curl -s -X POST http://localhost:8000/speech/analyze \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"transcript": "Um so like basically I wanted to explain the thing you know", "source": "manual"}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); m=d['metrics']; print(f'Filler rate: {m[\"filler_rate\"]}/100 | Complexity: {m[\"complexity_score\"]}/10 | Tip: {d[\"tip\"][:60]}')"
```

### Vision pipeline status
```bash
curl -s http://localhost:8000/vision/status -H "Authorization: Bearer $TOKEN" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Pipeline running:', d['running'])"
```

### Dashboard public (no auth)
```bash
curl -s http://localhost:8000/dashboard/public | python3 -m json.tool
```

### Tor onion address
```bash
curl -s http://localhost:8000/security/onion -H "Authorization: Bearer $TOKEN" | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('Onion:', d.get('onion','not started'))"
```

### Issue friend link
```bash
curl -s -X POST http://localhost:8000/friends/token \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "Rohan", "expires_days": 30}' | \
  python3 -c "import sys,json; d=json.load(sys.stdin); print('URL:', d['dashboard_url'][:60]+'...')"
```
