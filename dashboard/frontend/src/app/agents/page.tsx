"use client";

import { useState, useEffect, useRef } from "react";

const API = "http://localhost:8000";
const WS  = API.replace("http", "ws");

// ── Types ──────────────────────────────────────────────────────────────────────

interface LiveEvent {
  type: string;
  session_id?: string;
  agent?: string;
  task_id?: string;
  capability?: string;
  subtasks?: string[];
  response?: string;
  message?: string;
  success?: boolean;
}

interface AgentTask {
  id: string;
  created_at: number;
  status: string;
  task_type: string;
  payload: string;
  assigned_to: string;
}

// ── Auth ───────────────────────────────────────────────────────────────────────

async function getToken(): Promise<string> {
  const cached = sessionStorage.getItem("parv_token");
  if (cached) return cached;
  const r = await fetch(`${API}/auth/token`, { method: "POST" });
  const j = await r.json();
  sessionStorage.setItem("parv_token", j.access_token);
  return j.access_token;
}

async function apiFetch(path: string, opts: RequestInit = {}) {
  const token = await getToken();
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...opts.headers },
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

// ── Sub-components ─────────────────────────────────────────────────────────────

const AGENT_COLORS: Record<string, string> = {
  research:           "#3b82f6",
  music:              "#a855f7",
  reminder:           "#22c55e",
  email:              "#f59e0b",
  message:            "#06b6d4",
  sales_outreach:     "#ec4899",
  business_update:    "#f97316",
  project_planning:   "#8b5cf6",
  project_oversight:  "#ef4444",
  backend_review:     "#10b981",
  frontend_review:    "#6366f1",
  security_review:    "#dc2626",
  db_review:          "#0ea5e9",
  integration_check:  "#84cc16",
  browser:            "#64748b",
};

function AgentChip({ name }: { name: string }) {
  const color = AGENT_COLORS[name] ?? "#71717a";
  return (
    <span className="text-xs px-2 py-0.5 rounded-full font-mono"
      style={{ background: color + "22", color, border: `1px solid ${color}40` }}>
      {name}
    </span>
  );
}

function EventLine({ ev }: { ev: LiveEvent }) {
  let text = "";
  let color = "text-zinc-400";
  switch (ev.type) {
    case "jarvis_thinking":   text = "Jarvis is thinking...";              color = "text-blue-400"; break;
    case "jarvis_dispatching":
      text = `Dispatching to: ${(ev.subtasks ?? []).join(", ")}`;          color = "text-purple-400"; break;
    case "agent_started":     text = `▶ ${ev.agent} started`;              color = "text-cyan-400"; break;
    case "agent_done":        text = `✓ ${ev.agent} done — ${ev.success ? "ok" : "failed"}`; color = ev.success ? "text-green-400" : "text-red-400"; break;
    case "jarvis_done":       text = `✅ Jarvis: "${(ev.response ?? "").slice(0, 80)}"`;  color = "text-emerald-400"; break;
    case "jarvis_proactive":  text = `💡 Jarvis: "${(ev.message ?? "").slice(0, 80)}"`;  color = "text-yellow-400"; break;
    case "jarvis_response":   text = `Jarvis: "${(ev.response ?? "").slice(0, 80)}"`;    color = "text-zinc-200"; break;
    default:                  text = JSON.stringify(ev).slice(0, 90);
  }
  return <div className={`font-mono text-xs ${color}`}>{text}</div>;
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function AgentsPage() {
  const [input, setInput]         = useState("");
  const [running, setRunning]     = useState(false);
  const [events, setEvents]       = useState<LiveEvent[]>([]);
  const [tasks, setTasks]         = useState<AgentTask[]>([]);
  const [capabilities, setCaps]   = useState<string[]>([]);
  const [pending, setPending]     = useState(0);
  const [error, setError]         = useState("");
  const feedRef = useRef<HTMLDivElement>(null);
  const wsRef   = useRef<WebSocket | null>(null);

  useEffect(() => {
    apiFetch("/agents/status").then(d => {
      setCaps(d.capabilities ?? []);
      setPending(d.pending_tasks ?? 0);
    }).catch(() => {});
    apiFetch("/agents/tasks?limit=15").then(d => setTasks(d.tasks ?? [])).catch(() => {});
  }, []);

  useEffect(() => {
    const ws = new WebSocket(`${WS}/ws/agents`);
    wsRef.current = ws;
    ws.onmessage = (ev) => {
      try {
        const data: LiveEvent = JSON.parse(ev.data);
        if (data.type === "status") {
          setCaps((data as any).capabilities ?? []);
          setPending((data as any).pending ?? 0);
          return;
        }
        setEvents(prev => [...prev.slice(-150), data]);
        if (data.type === "jarvis_done") {
          setRunning(false);
          apiFetch("/agents/tasks?limit=15").then(d => setTasks(d.tasks ?? [])).catch(() => {});
        }
      } catch {}
    };
    const ping = setInterval(() => ws.readyState === WebSocket.OPEN && ws.send("ping"), 25000);
    return () => { clearInterval(ping); ws.close(); };
  }, []);

  useEffect(() => {
    feedRef.current?.scrollTo({ top: feedRef.current.scrollHeight, behavior: "smooth" });
  }, [events]);

  const submit = async () => {
    if (!input.trim() || running) return;
    setError("");
    setRunning(true);
    setEvents([]);
    try {
      await apiFetch("/agents/task", {
        method: "POST",
        body: JSON.stringify({ input: input.trim(), speak: true }),
      });
    } catch (e: any) {
      setError(e.message);
      setRunning(false);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      <div className="max-w-6xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">J.A.R.V.I.S.</h1>
            <p className="text-sm text-zinc-500 mt-1">
              Just A Rather Very Intelligent System — {capabilities.length} agents online
            </p>
          </div>
          <nav className="flex gap-2 text-sm text-zinc-400">
            {[["Dashboard","/"],["Dream","/dream"],["Learn","/learn"],
              ["Intelligence","/intelligence"],["Agents","/agents"],["Monitoring","/monitoring"]
            ].map(([l,h]) => (
              <a key={h} href={h} className={`px-3 py-1.5 rounded-lg hover:bg-zinc-800 transition-colors ${h==="/agents"?"text-blue-400":""}`}>{l}</a>
            ))}
          </nav>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left: Input + capabilities */}
          <div className="space-y-4">

            {/* Task input */}
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 space-y-3">
              <h2 className="text-sm font-semibold text-zinc-200">Tell Jarvis</h2>
              <textarea
                value={input}
                onChange={e => setInput(e.target.value)}
                onKeyDown={e => e.key === "Enter" && !e.shiftKey && (e.preventDefault(), submit())}
                placeholder="e.g. Check my emails, research quantum computing, review the backend code..."
                rows={4}
                className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500 resize-none"
              />
              {error && <p className="text-xs text-red-400">{error}</p>}
              <button
                onClick={submit}
                disabled={running || !input.trim()}
                className="w-full py-2 rounded-lg text-sm font-medium bg-blue-600 hover:bg-blue-500 text-white disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
              >
                {running ? (
                  <span className="flex items-center justify-center gap-2">
                    <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
                    Jarvis is working...
                  </span>
                ) : "Send to Jarvis"}
              </button>
            </div>

            {/* Pending indicator */}
            {pending > 0 && (
              <div className="bg-yellow-900/20 border border-yellow-700/40 rounded-xl px-4 py-3 text-xs text-yellow-400">
                {pending} task{pending > 1 ? "s" : ""} pending in queue
              </div>
            )}

            {/* Capabilities grid */}
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Agents Online</h2>
              <div className="flex flex-wrap gap-2">
                {capabilities.map(c => <AgentChip key={c} name={c} />)}
              </div>
            </div>
          </div>

          {/* Right: Live feed + task history */}
          <div className="lg:col-span-2 space-y-4">

            {/* Live feed */}
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Live Feed</h2>
              <div
                ref={feedRef}
                className="h-64 overflow-y-auto space-y-1 bg-zinc-950 rounded-lg p-3"
              >
                {events.length === 0 ? (
                  <p className="text-xs text-zinc-600 font-mono">Waiting for Jarvis...</p>
                ) : (
                  events.map((ev, i) => <EventLine key={i} ev={ev} />)
                )}
              </div>
            </div>

            {/* Task history */}
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">Recent Tasks</h2>
              {tasks.length === 0 ? (
                <p className="text-xs text-zinc-600">No tasks yet.</p>
              ) : (
                <div className="space-y-2">
                  {tasks.map(t => (
                    <div key={t.id} className="flex items-center justify-between bg-zinc-800 rounded-lg px-3 py-2">
                      <div className="flex items-center gap-2 min-w-0">
                        <AgentChip name={t.task_type} />
                        <span className="text-xs text-zinc-400 truncate">{t.assigned_to || "pending"}</span>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <span className={`text-xs px-2 py-0.5 rounded-full ${
                          t.status === "done"    ? "bg-green-900/40 text-green-400" :
                          t.status === "running" ? "bg-blue-900/40 text-blue-400 animate-pulse" :
                          t.status === "failed"  ? "bg-red-900/40 text-red-400" :
                          "bg-zinc-700 text-zinc-400"
                        }`}>{t.status}</span>
                        <span className="text-xs text-zinc-600">
                          {new Date(t.created_at * 1000).toLocaleTimeString("en-US", {hour:"2-digit",minute:"2-digit"})}
                        </span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
