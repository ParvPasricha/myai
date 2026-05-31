"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  RadarChart, Radar, PolarGrid, PolarAngleAxis,
  ResponsiveContainer, Tooltip,
} from "recharts";

const API = "http://localhost:8000";
const WS  = API.replace("http", "ws");

// ── Types ─────────────────────────────────────────────────────────────────────

interface Problem {
  difficulty: "easy" | "medium" | "hard";
  problem: string;
  approach: string;
  common_mistake: string;
}

interface Critique {
  correctness: number;
  clarity: number;
  depth: number;
  critique: string;
}

interface Concept {
  id: string;
  subtopic: string;
  derivation: string;
  problems: Problem[];
  critique: Critique;
  score: number;
}

interface GdleSession {
  id: string;
  topic: string;
  depth: string;
  started_at: number;
  finished_at?: number;
  status: string;
  avg_score?: number;
  guide?: string;
  concepts?: Concept[];
}

interface LiveEvent {
  type: string;
  session_id?: string;
  topic?: string;
  subtopics?: string[];
  concept_id?: string;
  subtopic?: string;
  score?: number;
  problems_count?: number;
  critique_preview?: string;
  avg_score?: number;
  guide?: string;
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

async function apiFetch(path: string, opts: RequestInit = {}) {
  const token = await getToken();
  const r = await fetch(`${API}${path}`, {
    ...opts,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...opts.headers },
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
}

// ── Sub-components ────────────────────────────────────────────────────────────

const DEPTH_OPTIONS = ["beginner", "intermediate", "advanced", "expert"] as const;
type Depth = typeof DEPTH_OPTIONS[number];

const DEPTH_COLOR: Record<Depth, string> = {
  beginner:     "#22c55e",
  intermediate: "#3b82f6",
  advanced:     "#f59e0b",
  expert:       "#ef4444",
};

function DiffBadge({ d }: { d: string }) {
  const colors: Record<string, string> = {
    easy:   "bg-green-900/40 text-green-300",
    medium: "bg-yellow-900/40 text-yellow-300",
    hard:   "bg-red-900/40 text-red-300",
  };
  return (
    <span className={`text-xs px-2 py-0.5 rounded-full font-mono ${colors[d] ?? "bg-zinc-700 text-zinc-300"}`}>
      {d}
    </span>
  );
}

function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value * 100);
  const color = value >= 0.75 ? "#22c55e" : value >= 0.5 ? "#f59e0b" : "#ef4444";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-24 text-zinc-400 shrink-0">{label}</span>
      <div className="flex-1 h-1.5 bg-zinc-700 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, background: color }} />
      </div>
      <span className="w-8 text-right text-zinc-300">{pct}%</span>
    </div>
  );
}

function ConceptCard({ concept }: { concept: Concept }) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"derivation" | "problems" | "critique">("derivation");
  const score = concept.score ?? 0;
  const scoreColor = score >= 0.75 ? "#22c55e" : score >= 0.5 ? "#f59e0b" : "#ef4444";

  const radarData = concept.critique ? [
    { axis: "Correctness", value: Math.round((concept.critique.correctness ?? 0) * 100) },
    { axis: "Clarity",     value: Math.round((concept.critique.clarity     ?? 0) * 100) },
    { axis: "Depth",       value: Math.round((concept.critique.depth       ?? 0) * 100) },
  ] : [];

  return (
    <div className="bg-zinc-800 border border-zinc-700 rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full flex items-center justify-between px-4 py-3 text-left hover:bg-zinc-750 transition-colors"
      >
        <span className="text-sm font-medium text-zinc-100 truncate pr-4">{concept.subtopic}</span>
        <div className="flex items-center gap-3 shrink-0">
          <span className="text-xs font-mono" style={{ color: scoreColor }}>
            {Math.round(score * 100)}%
          </span>
          <span className="text-zinc-500 text-xs">{concept.problems?.length ?? 0} problems</span>
          <svg
            className={`w-4 h-4 text-zinc-500 transition-transform ${open ? "rotate-180" : ""}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
          >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {open && (
        <div className="border-t border-zinc-700 px-4 pb-4">
          <div className="flex gap-1 mt-3 mb-4">
            {(["derivation", "problems", "critique"] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                className={`px-3 py-1 rounded text-xs capitalize transition-colors ${
                  tab === t
                    ? "bg-blue-600 text-white"
                    : "bg-zinc-700 text-zinc-400 hover:bg-zinc-600"
                }`}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === "derivation" && (
            <pre className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
              {concept.derivation}
            </pre>
          )}

          {tab === "problems" && (
            <div className="space-y-3">
              {(concept.problems ?? []).map((p, i) => (
                <div key={i} className="bg-zinc-900 rounded-lg p-3 space-y-2">
                  <div className="flex items-center gap-2">
                    <DiffBadge d={p.difficulty} />
                  </div>
                  <p className="text-sm text-zinc-100">{p.problem}</p>
                  <div className="text-xs text-zinc-400">
                    <span className="text-zinc-500">Approach: </span>{p.approach}
                  </div>
                  <div className="text-xs text-amber-400/80">
                    <span className="text-zinc-500">Common mistake: </span>{p.common_mistake}
                  </div>
                </div>
              ))}
              {(!concept.problems || concept.problems.length === 0) && (
                <p className="text-xs text-zinc-500">No problems generated.</p>
              )}
            </div>
          )}

          {tab === "critique" && concept.critique && (
            <div className="space-y-4">
              <div className="space-y-2">
                <ScoreBar label="Correctness" value={concept.critique.correctness ?? 0} />
                <ScoreBar label="Clarity"     value={concept.critique.clarity ?? 0} />
                <ScoreBar label="Depth"       value={concept.critique.depth ?? 0} />
              </div>
              {radarData.length > 0 && (
                <div className="h-40">
                  <ResponsiveContainer width="100%" height="100%">
                    <RadarChart data={radarData}>
                      <PolarGrid stroke="#3f3f46" />
                      <PolarAngleAxis dataKey="axis" tick={{ fill: "#71717a", fontSize: 10 }} />
                      <Radar dataKey="value" stroke="#3b82f6" fill="#3b82f6" fillOpacity={0.25} />
                      <Tooltip
                        contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8 }}
                        formatter={(v) => [`${v}%`]}
                      />
                    </RadarChart>
                  </ResponsiveContainer>
                </div>
              )}
              {concept.critique.critique && (
                <div className="bg-red-900/20 border border-red-800/40 rounded-lg p-3 text-xs text-red-300">
                  <span className="font-medium text-red-400">Critique: </span>
                  {concept.critique.critique}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function SessionSummary({ session, onSelect }: { session: GdleSession; onSelect: () => void }) {
  const score = session.avg_score ?? 0;
  const scoreColor = score >= 0.75 ? "#22c55e" : score >= 0.5 ? "#f59e0b" : "#ef4444";
  const depthColor = DEPTH_COLOR[session.depth as Depth] ?? "#71717a";

  return (
    <button
      onClick={onSelect}
      className="w-full text-left bg-zinc-800 hover:bg-zinc-750 border border-zinc-700 rounded-xl p-4 transition-colors"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-100 truncate">{session.topic}</p>
          <p className="text-xs text-zinc-500 mt-1">
            {new Date(session.started_at * 1000).toLocaleDateString("en-US", {
              month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
            })}
          </p>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          <span className="text-xs px-2 py-0.5 rounded-full border" style={{ color: depthColor, borderColor: depthColor + "40" }}>
            {session.depth}
          </span>
          {session.avg_score !== undefined && (
            <span className="text-xs font-mono" style={{ color: scoreColor }}>
              {Math.round(score * 100)}%
            </span>
          )}
          <span className={`text-xs px-2 py-0.5 rounded-full ${
            session.status === "done"    ? "bg-green-900/40 text-green-400" :
            session.status === "running" ? "bg-blue-900/40 text-blue-400"  :
            "bg-red-900/40 text-red-400"
          }`}>
            {session.status}
          </span>
        </div>
      </div>
    </button>
  );
}

// ── Live feed ─────────────────────────────────────────────────────────────────

function LiveFeed({ events }: { events: LiveEvent[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => { endRef.current?.scrollIntoView({ behavior: "smooth" }); }, [events]);

  if (events.length === 0) return null;

  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 h-48 overflow-y-auto font-mono text-xs space-y-1">
      {events.map((e, i) => {
        let line = "";
        let color = "text-zinc-400";
        switch (e.type) {
          case "gdle_start":        line = `▶ Session started — ${e.topic}`; color = "text-blue-400"; break;
          case "gdle_concept_map":  line = `📋 Concept map: ${(e.subtopics ?? []).join(", ")}`; color = "text-purple-400"; break;
          case "gdle_concept_done": line = `✓ ${e.subtopic} — ${Math.round((e.score ?? 0) * 100)}% · ${e.problems_count} problems`; color = "text-green-400"; break;
          case "gdle_guide_start":  line = "📝 Building learning guide..."; color = "text-yellow-400"; break;
          case "gdle_done":         line = `✅ Done — avg score ${Math.round((e.avg_score ?? 0) * 100)}%`; color = "text-emerald-400"; break;
          default:                  line = JSON.stringify(e).slice(0, 80);
        }
        return <div key={i} className={color}>{line}</div>;
      })}
      <div ref={endRef} />
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function LearnPage() {
  const [topic, setTopic]           = useState("");
  const [depth, setDepth]           = useState<Depth>("intermediate");
  const [style, setStyle]           = useState("");
  const [constraints, setConstraints] = useState("");
  const [running, setRunning]       = useState(false);
  const [liveEvents, setLiveEvents] = useState<LiveEvent[]>([]);
  const [sessions, setSessions]     = useState<GdleSession[]>([]);
  const [selected, setSelected]     = useState<GdleSession | null>(null);
  const [loadingSession, setLoadingSession] = useState(false);
  const [error, setError]           = useState("");
  const wsRef = useRef<WebSocket | null>(null);

  // Load sessions on mount
  useEffect(() => {
    apiFetch("/gdle/sessions").then(d => setSessions(d.sessions ?? [])).catch(() => {});
  }, []);

  // WebSocket connection
  useEffect(() => {
    const token = sessionStorage.getItem("parv_token");
    const ws = new WebSocket(`${WS}/ws/gdle`);
    wsRef.current = ws;

    ws.onmessage = (ev) => {
      try {
        const data: LiveEvent = JSON.parse(ev.data);
        if (data.type !== "status") {
          setLiveEvents(prev => [...prev.slice(-100), data]);
        }
        if (data.type === "gdle_done") {
          setRunning(false);
          apiFetch("/gdle/sessions").then(d => setSessions(d.sessions ?? [])).catch(() => {});
        }
      } catch {}
    };

    const ping = setInterval(() => { ws.readyState === WebSocket.OPEN && ws.send("ping"); }, 25000);
    return () => { clearInterval(ping); ws.close(); };
  }, []);

  const startSession = async () => {
    if (!topic.trim()) return;
    setError("");
    setRunning(true);
    setLiveEvents([]);
    setSelected(null);
    try {
      await apiFetch("/gdle/start", {
        method: "POST",
        body: JSON.stringify({ topic: topic.trim(), depth, style, constraints }),
      });
    } catch (e: any) {
      setError(e.message);
      setRunning(false);
    }
  };

  const selectSession = async (s: GdleSession) => {
    setLoadingSession(true);
    try {
      const full = await apiFetch(`/gdle/session/${s.id}`);
      setSelected(full);
    } catch {
      setSelected(s);
    } finally {
      setLoadingSession(false);
    }
  };

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100 p-6">
      <div className="max-w-5xl mx-auto space-y-6">

        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold tracking-tight">Guided Learning Engine</h1>
            <p className="text-sm text-zinc-500 mt-1">
              Deep concept sessions — derivation, problems, critique, personalized guide
            </p>
          </div>
          <nav className="flex gap-2 text-sm text-zinc-400">
            {[
              ["Dashboard", "/"],
              ["Dream", "/dream"],
              ["Learn", "/learn"],
              ["Intelligence", "/intelligence"],
              ["Monitoring", "/monitoring"],
            ].map(([label, href]) => (
              <a key={href} href={href}
                className={`px-3 py-1.5 rounded-lg hover:bg-zinc-800 transition-colors ${href === "/learn" ? "text-blue-400" : ""}`}>
                {label}
              </a>
            ))}
          </nav>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

          {/* Left: Start form + session history */}
          <div className="space-y-4">

            {/* Start form */}
            <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4 space-y-4">
              <h2 className="text-sm font-semibold text-zinc-200">New Session</h2>

              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Topic</label>
                <input
                  value={topic}
                  onChange={e => setTopic(e.target.value)}
                  placeholder="e.g. Transformer attention mechanisms"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
                  onKeyDown={e => e.key === "Enter" && !running && startSession()}
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Depth</label>
                <div className="grid grid-cols-2 gap-2">
                  {DEPTH_OPTIONS.map(d => (
                    <button
                      key={d}
                      onClick={() => setDepth(d)}
                      className={`py-1.5 rounded-lg text-xs capitalize border transition-colors ${
                        depth === d
                          ? "border-transparent text-white"
                          : "border-zinc-700 text-zinc-400 hover:border-zinc-500"
                      }`}
                      style={depth === d ? { background: DEPTH_COLOR[d] + "33", borderColor: DEPTH_COLOR[d], color: DEPTH_COLOR[d] } : {}}
                    >
                      {d}
                    </button>
                  ))}
                </div>
              </div>

              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Style <span className="text-zinc-600">(optional)</span></label>
                <input
                  value={style}
                  onChange={e => setStyle(e.target.value)}
                  placeholder="e.g. visual, math-heavy, code examples"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
                />
              </div>

              <div className="space-y-2">
                <label className="text-xs text-zinc-400">Constraints <span className="text-zinc-600">(optional)</span></label>
                <input
                  value={constraints}
                  onChange={e => setConstraints(e.target.value)}
                  placeholder="e.g. no calculus, focus on PyTorch"
                  className="w-full bg-zinc-800 border border-zinc-700 rounded-lg px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-blue-500"
                />
              </div>

              {error && <p className="text-xs text-red-400">{error}</p>}

              <button
                onClick={startSession}
                disabled={running || !topic.trim()}
                className="w-full py-2 rounded-lg text-sm font-medium transition-colors disabled:opacity-40 disabled:cursor-not-allowed bg-blue-600 hover:bg-blue-500 text-white"
              >
                {running ? "Running..." : "Start Learning Session"}
              </button>
            </div>

            {/* Live feed */}
            {liveEvents.length > 0 && <LiveFeed events={liveEvents} />}

            {/* Session history */}
            <div className="space-y-2">
              <h2 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">Recent Sessions</h2>
              {sessions.length === 0 ? (
                <p className="text-xs text-zinc-600">No sessions yet.</p>
              ) : (
                sessions.map(s => (
                  <SessionSummary key={s.id} session={s} onSelect={() => selectSession(s)} />
                ))
              )}
            </div>
          </div>

          {/* Right: Session detail */}
          <div className="lg:col-span-2">
            {!selected && !loadingSession && (
              <div className="h-full flex items-center justify-center text-zinc-600 text-sm">
                {running ? (
                  <div className="text-center space-y-2">
                    <div className="w-8 h-8 border-2 border-blue-500 border-t-transparent rounded-full animate-spin mx-auto" />
                    <p>Session running — results appear here when done</p>
                  </div>
                ) : (
                  <p>Select a session or start a new one</p>
                )}
              </div>
            )}

            {loadingSession && (
              <div className="h-full flex items-center justify-center">
                <div className="w-6 h-6 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
              </div>
            )}

            {selected && !loadingSession && (
              <div className="space-y-4">

                {/* Session header */}
                <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div>
                      <h2 className="text-lg font-semibold text-zinc-100">{selected.topic}</h2>
                      <div className="flex items-center gap-3 mt-1">
                        <span className="text-xs text-zinc-500">
                          {new Date(selected.started_at * 1000).toLocaleDateString("en-US", {
                            month: "short", day: "numeric",
                            hour: "2-digit", minute: "2-digit",
                          })}
                        </span>
                        <span
                          className="text-xs px-2 py-0.5 rounded-full border capitalize"
                          style={{
                            color: DEPTH_COLOR[selected.depth as Depth] ?? "#71717a",
                            borderColor: (DEPTH_COLOR[selected.depth as Depth] ?? "#71717a") + "40",
                          }}
                        >
                          {selected.depth}
                        </span>
                        {selected.avg_score !== undefined && (
                          <span className="text-xs font-mono text-zinc-300">
                            avg {Math.round(selected.avg_score * 100)}%
                          </span>
                        )}
                      </div>
                    </div>
                    <button
                      onClick={() => setSelected(null)}
                      className="text-zinc-500 hover:text-zinc-300 text-xs"
                    >
                      ✕
                    </button>
                  </div>
                </div>

                {/* Learning guide */}
                {selected.guide && (
                  <div className="bg-zinc-900 border border-zinc-700 rounded-xl p-4">
                    <h3 className="text-sm font-semibold text-zinc-200 mb-3">Learning Guide</h3>
                    <pre className="text-xs text-zinc-300 whitespace-pre-wrap leading-relaxed">
                      {selected.guide}
                    </pre>
                  </div>
                )}

                {/* Concepts */}
                {(selected.concepts ?? []).length > 0 && (
                  <div className="space-y-2">
                    <h3 className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
                      Concepts ({selected.concepts!.length})
                    </h3>
                    {selected.concepts!.map(c => (
                      <ConceptCard key={c.id} concept={c} />
                    ))}
                  </div>
                )}

                {(!selected.concepts || selected.concepts.length === 0) && selected.status === "done" && (
                  <p className="text-xs text-zinc-600">No concepts found for this session.</p>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
