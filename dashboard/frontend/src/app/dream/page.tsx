"use client";

import { useState, useEffect, useRef } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip,
  LineChart, Line, ResponsiveContainer, CartesianGrid,
} from "recharts";

const API = "http://localhost:8000";
const WS  = API.replace("http", "ws");

// ── Types ─────────────────────────────────────────────────────────────────────

interface DreamTask {
  id: string;
  strategy: string;
  prompt: string;
  response: string;
  score_consistency: number;
  score_novelty: number;
  score_usefulness: number;
  score_safety: number;
  score_composite: number;
  approved: number;
  rejection_reason: string;
}

interface DreamSession {
  id: string;
  started_at: number;
  finished_at?: number;
  tasks_total: number;
  tasks_approved: number;
  status: string;
  tasks?: DreamTask[];
}

interface LiveEvent {
  type: string;
  task_id?: string;
  strategy?: string;
  approved?: boolean;
  scores?: Record<string, number>;
  response_preview?: string;
  session_id?: string;
  total?: number;
  approved_count?: number;
}

// ── Auth ──────────────────────────────────────────────────────────────────────

async function getToken(): Promise<string> {
  const cached = sessionStorage.getItem("parv_token");
  if (cached) return cached;
  const r = await fetch(`${API}/auth/token`, { method: "POST" });
  const j = await r.json();
  sessionStorage.setItem("parv_token", j.access_token);
  return j.access_token;
}

function h() {
  const tok = sessionStorage.getItem("parv_token") ?? "";
  return { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" };
}

// ── Colours ───────────────────────────────────────────────────────────────────

const STRATEGY_COLOR: Record<string, string> = {
  remix:         "#3b82f6",
  blend:         "#a855f7",
  edge_case:     "#f97316",
  contradiction: "#06b6d4",
};

const STRATEGY_LABEL: Record<string, string> = {
  remix:         "Remix",
  blend:         "Blend",
  edge_case:     "Edge Case",
  contradiction: "Contradiction",
};

// ── Components ────────────────────────────────────────────────────────────────

function ModeBanner({ mode, active }: { mode: string; active: string | null }) {
  const colors: Record<string, string> = {
    wake:     "bg-zinc-800 text-zinc-300",
    dreaming: "bg-purple-900/50 text-purple-300 border border-purple-700",
    idle:     "bg-zinc-800 text-zinc-500",
  };
  return (
    <div className={`flex items-center gap-3 px-4 py-2 rounded-xl ${colors[mode] ?? colors.idle}`}>
      {mode === "dreaming" && (
        <div className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
      )}
      <span className="text-sm font-semibold capitalize">{mode}</span>
      {active && <span className="text-xs opacity-60 font-mono">session {active}</span>}
    </div>
  );
}

function ScoreBar({ label, value, color }: { label: string; value: number; color: string }) {
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-20 text-zinc-500 text-right">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${value * 100}%`, background: color }} />
      </div>
      <span className="w-8 text-zinc-400 font-mono">{value.toFixed(2)}</span>
    </div>
  );
}

function TaskCard({ task }: { task: DreamTask }) {
  const [expanded, setExpanded] = useState(false);
  const color = STRATEGY_COLOR[task.strategy] ?? "#71717a";
  const passed = task.approved === 1;

  return (
    <div
      className={`rounded-xl border p-3 cursor-pointer transition-all ${
        passed
          ? "border-green-900 bg-green-950/30"
          : "border-zinc-800 bg-zinc-900/40"
      }`}
      onClick={() => setExpanded(e => !e)}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="text-xs font-semibold px-2 py-0.5 rounded-full"
              style={{ background: color + "22", color }}>
          {STRATEGY_LABEL[task.strategy] ?? task.strategy}
        </span>
        <span className={`ml-auto text-xs font-mono font-bold ${passed ? "text-green-400" : "text-zinc-600"}`}>
          {task.score_composite?.toFixed(3) ?? "—"}
        </span>
        {passed
          ? <span className="text-green-500 text-xs">✓</span>
          : <span className="text-red-500 text-xs">✗</span>
        }
      </div>

      <p className="text-zinc-300 text-xs leading-snug line-clamp-2">{task.prompt}</p>

      {!passed && task.rejection_reason && (
        <p className="text-red-400 text-xs mt-1 opacity-70">{task.rejection_reason}</p>
      )}

      {expanded && (
        <div className="mt-3 space-y-2 border-t border-zinc-800 pt-3">
          <p className="text-zinc-200 text-xs leading-relaxed">{task.response}</p>
          <div className="space-y-1 mt-2">
            <ScoreBar label="Consistency" value={task.score_consistency ?? 0} color="#3b82f6" />
            <ScoreBar label="Novelty"     value={task.score_novelty ?? 0}     color="#a855f7" />
            <ScoreBar label="Usefulness"  value={task.score_usefulness ?? 0}  color="#22c55e" />
            <ScoreBar label="Safety"      value={task.score_safety ?? 0}      color="#f59e0b" />
          </div>
        </div>
      )}
    </div>
  );
}

function LiveFeed({ events }: { events: LiveEvent[] }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [events]);

  return (
    <div ref={ref} className="h-48 overflow-y-auto space-y-1.5 font-mono text-xs">
      {events.length === 0 && (
        <p className="text-zinc-700 italic">Waiting for dream session…</p>
      )}
      {events.map((e, i) => (
        <div key={i} className="flex gap-2 text-zinc-400">
          <span className="text-zinc-600 w-16 flex-shrink-0">{e.type}</span>
          {e.type === "dream_task_done" && (
            <span>
              <span style={{ color: STRATEGY_COLOR[e.strategy ?? ""] }}>[{e.strategy}]</span>
              {" "}
              <span className={e.approved ? "text-green-400" : "text-red-400"}>
                {e.approved ? "✓" : "✗"}
              </span>
              {" "}
              <span className="text-zinc-500">
                {e.scores?.composite?.toFixed(3)}
              </span>
              {" — "}
              <span className="text-zinc-500 truncate">
                {e.response_preview?.slice(0, 60)}
              </span>
            </span>
          )}
          {e.type === "dream_session_start" && (
            <span className="text-purple-400">Session {e.session_id} starting…</span>
          )}
          {e.type === "dream_session_done" && (
            <span className="text-green-400">
              Done — {e.approved_count}/{e.total} approved
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function DreamPage() {
  const [mode, setMode]         = useState("wake");
  const [active, setActive]     = useState<string | null>(null);
  const [sessions, setSessions] = useState<DreamSession[]>([]);
  const [selected, setSelected] = useState<DreamSession | null>(null);
  const [approved, setApproved] = useState<DreamTask[]>([]);
  const [events, setEvents]     = useState<LiveEvent[]>([]);
  const [triggering, setTriggering] = useState(false);
  const [connected, setConnected]   = useState(false);

  // Load initial data
  useEffect(() => {
    getToken().then(async () => {
      await loadSessions();
      await loadApproved();
      await loadStatus();
    });
  }, []);

  // WebSocket
  useEffect(() => {
    let ws: WebSocket;
    const connect = () => {
      ws = new WebSocket(`${WS}/ws/dream`);
      ws.onopen  = () => setConnected(true);
      ws.onclose = () => { setConnected(false); setTimeout(connect, 3000); };
      ws.onmessage = (e) => {
        const data: LiveEvent = JSON.parse(e.data);
        setEvents(prev => [...prev.slice(-99), data]);
        if (data.type === "dream_session_start") {
          setMode("dreaming");
          setActive(data.session_id ?? null);
        }
        if (data.type === "dream_session_done") {
          setMode("wake");
          setActive(null);
          loadSessions();
          loadApproved();
        }
      };
    };
    connect();
    return () => ws?.close();
  }, []);

  const loadSessions = async () => {
    const r = await fetch(`${API}/dream/sessions?n=10`, { headers: h() });
    const j = await r.json();
    setSessions(j.sessions ?? []);
  };

  const loadApproved = async () => {
    const r = await fetch(`${API}/dream/approved?n=20`, { headers: h() });
    const j = await r.json();
    setApproved(j.dreams ?? []);
  };

  const loadStatus = async () => {
    const r = await fetch(`${API}/dream/status`, { headers: h() });
    const j = await r.json();
    setMode(j.mode);
    setActive(j.active_session);
  };

  const loadSession = async (id: string) => {
    const r = await fetch(`${API}/dream/session/${id}`, { headers: h() });
    setSelected(await r.json());
  };

  const triggerDream = async () => {
    setTriggering(true);
    await fetch(`${API}/dream/run`, { method: "POST", headers: h() });
    setTriggering(false);
    setMode("dreaming");
  };

  const removeApproved = async (id: string) => {
    await fetch(`${API}/dream/approved/${id}`, { method: "DELETE", headers: h() });
    setApproved(prev => prev.filter(d => d.id !== id));
  };

  // Score bar chart data for selected session
  const chartData = selected?.tasks?.map(t => ({
    name: t.strategy.slice(0, 4),
    score: +(t.score_composite ?? 0).toFixed(3),
    fill: t.approved ? "#22c55e" : "#3f3f46",
  })) ?? [];

  return (
    <main className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
        <div>
          <h1 className="text-lg font-bold tracking-tight">Dream System</h1>
          <p className="text-zinc-600 text-xs mt-0.5">
            Synthetic memory generation · nightly 3am · manual trigger available
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className={`w-2 h-2 rounded-full ${connected ? "bg-green-400" : "bg-zinc-600"}`} />
          <ModeBanner mode={mode} active={active} />
          <button
            onClick={triggerDream}
            disabled={triggering || mode === "dreaming"}
            className="text-xs px-3 py-1.5 rounded-lg bg-purple-700 hover:bg-purple-600
                       disabled:opacity-30 text-white font-semibold transition-colors"
          >
            {triggering ? "Starting…" : "Run now"}
          </button>
        </div>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-6 grid grid-cols-1 lg:grid-cols-3 gap-6">

        {/* Left — sessions list */}
        <div className="space-y-4">
          <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
            Sessions
          </h2>
          {sessions.length === 0 && (
            <p className="text-zinc-600 text-sm">No sessions yet — click Run now.</p>
          )}
          {sessions.map(s => (
            <button
              key={s.id}
              onClick={() => loadSession(s.id)}
              className={`w-full text-left p-3 rounded-xl border transition-colors ${
                selected?.id === s.id
                  ? "border-purple-700 bg-purple-950/30"
                  : "border-zinc-800 bg-zinc-900 hover:border-zinc-700"
              }`}
            >
              <div className="flex justify-between items-center mb-1">
                <span className="text-xs font-mono text-zinc-400">{s.id}</span>
                <span className={`text-xs px-1.5 py-0.5 rounded ${
                  s.status === "done" ? "bg-green-900 text-green-300" :
                  s.status === "running" ? "bg-purple-900 text-purple-300" :
                  "bg-red-900 text-red-300"
                }`}>{s.status}</span>
              </div>
              <div className="text-xs text-zinc-500">
                {s.tasks_approved}/{s.tasks_total} approved ·{" "}
                {new Date(s.started_at * 1000).toLocaleString()}
              </div>
            </button>
          ))}
        </div>

        {/* Centre — session detail */}
        <div className="lg:col-span-2 space-y-5">

          {/* Live feed */}
          <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
            <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
              Live feed
            </p>
            <LiveFeed events={events} />
          </div>

          {selected ? (
            <>
              {/* Score chart */}
              <div className="bg-zinc-900 border border-zinc-800 rounded-xl p-4">
                <p className="text-xs text-zinc-500 mb-3">
                  Task scores — {selected.tasks_approved}/{selected.tasks_total} approved
                </p>
                {chartData.length > 0 && (
                  <ResponsiveContainer width="100%" height={80}>
                    <BarChart data={chartData} margin={{ top: 0, right: 8, bottom: 0, left: -20 }}>
                      <YAxis domain={[0, 1]} tick={{ fontSize: 9, fill: "#52525b" }} />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", fontSize: 11 }}
                      />
                      {/* Pass line */}
                      <Bar dataKey="score" radius={[3,3,0,0]}
                           fill="#3f3f46"
                           label={false}>
                        {chartData.map((d, i) => (
                          <rect key={i} fill={d.fill} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                )}
              </div>

              {/* Tasks */}
              <div>
                <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
                  Tasks — click to expand
                </p>
                <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                  {(selected.tasks ?? []).map(t => (
                    <TaskCard key={t.id} task={t} />
                  ))}
                </div>
              </div>
            </>
          ) : (
            /* Approved patterns */
            <div>
              <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-3">
                Approved patterns in memory ({approved.length})
              </p>
              {approved.length === 0 && (
                <p className="text-zinc-600 text-sm">
                  Run a dream session to generate approved patterns.
                </p>
              )}
              <div className="space-y-2 max-h-[600px] overflow-y-auto pr-1">
                {approved.map(d => (
                  <div key={d.id}
                    className="bg-zinc-900 border border-zinc-800 rounded-xl p-3 group">
                    <div className="flex items-center gap-2 mb-2">
                      <span className="text-xs px-2 py-0.5 rounded-full"
                            style={{
                              background: (STRATEGY_COLOR[d.strategy] ?? "#71717a") + "22",
                              color: STRATEGY_COLOR[d.strategy] ?? "#71717a",
                            }}>
                        {STRATEGY_LABEL[d.strategy] ?? d.strategy}
                      </span>
                      <span className="text-xs font-mono text-green-400 ml-auto">
                        {d.score_composite?.toFixed(3)}
                      </span>
                      <button
                        onClick={() => removeApproved(d.id)}
                        className="text-zinc-700 hover:text-red-400 text-xs opacity-0 group-hover:opacity-100 transition-opacity"
                      >
                        ✕
                      </button>
                    </div>
                    <p className="text-zinc-300 text-xs leading-relaxed line-clamp-3">
                      {d.response}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
