"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, XAxis, YAxis, Tooltip,
  BarChart, Bar, ResponsiveContainer, CartesianGrid,
} from "recharts";
import { ArcGauge } from "@/components/ArcGauge";
import { useMetrics, fetchHistory, HistoryPoint } from "@/lib/useMetrics";

// ── Colours ───────────────────────────────────────────────────────────────────
const C = {
  focus:  "#3b82f6",
  energy: "#22c55e",
  stress: "#f97316",
  purple: "#a855f7",
  zinc:   "#52525b",
};

// ── Small reusable pieces ─────────────────────────────────────────────────────

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section>
      <h2 className="text-xs font-semibold tracking-widest text-zinc-500 uppercase mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function Card({ children, className = "" }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-zinc-900 border border-zinc-800 rounded-xl p-4 ${className}`}>
      {children}
    </div>
  );
}

function StatTile({
  label, value, sub, color = "white",
}: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <Card>
      <p className="text-zinc-500 text-xs mb-1">{label}</p>
      <p className="text-2xl font-bold tracking-tight" style={{ color }}>{value}</p>
      {sub && <p className="text-zinc-600 text-xs mt-0.5">{sub}</p>}
    </Card>
  );
}

function ServiceBadge({ label, alive }: { label: string; alive: boolean }) {
  return (
    <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border ${
      alive ? "border-green-900 bg-green-950" : "border-red-900 bg-red-950"
    }`}>
      <div className={`w-2 h-2 rounded-full ${alive ? "bg-green-400" : "bg-red-500"}`} />
      <span className="text-xs font-medium text-zinc-300">{label}</span>
    </div>
  );
}

function DeadManGauge({ seconds }: { seconds: number }) {
  const max = 300;
  const pct = Math.min(seconds / max, 1);
  const color = seconds < 60 ? "#ef4444" : seconds < 120 ? "#f97316" : "#22c55e";
  const W = 220;
  const H = 24;
  return (
    <div className="flex flex-col gap-1.5">
      <div className="flex justify-between text-xs text-zinc-500">
        <span>Dead man switch</span>
        <span style={{ color }} className="font-mono font-semibold">{seconds}s</span>
      </div>
      <div className="w-full h-2.5 bg-zinc-800 rounded-full overflow-hidden">
        <div
          className="h-full rounded-full transition-all duration-700"
          style={{ width: `${pct * 100}%`, background: color }}
        />
      </div>
      <p className="text-zinc-600 text-xs">
        {seconds < 60 ? "⚠ Vault will lock soon" : "Vault armed"}
      </p>
    </div>
  );
}

// Custom recharts tooltip
function ChartTip({ active, payload, label, unit = "" }: any) {
  if (!active || !payload?.length) return null;
  const t = new Date(label * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return (
    <div className="bg-zinc-900 border border-zinc-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <p className="text-zinc-400 mb-1">{t}</p>
      {payload.map((p: any) => (
        <p key={p.dataKey} style={{ color: p.color }}>
          {p.name}: <span className="font-mono">{Number(p.value).toFixed(2)}{unit}</span>
        </p>
      ))}
    </div>
  );
}

// ── Brain state history hook ──────────────────────────────────────────────────
function useBrainHistory() {
  const [history, setHistory] = useState<{
    focus: HistoryPoint[]; energy: HistoryPoint[]; stress: HistoryPoint[];
  }>({ focus: [], energy: [], stress: [] });

  useEffect(() => {
    const load = async () => {
      const [f, e, s] = await Promise.all([
        fetchHistory("focus"),
        fetchHistory("energy"),
        fetchHistory("stress"),
      ]);
      setHistory({ focus: f, energy: e, stress: s });
    };
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);

  // Merge into one array keyed by ts
  const merged = history.focus.map((p, i) => ({
    ts: p.ts,
    focus:  p.value,
    energy: history.energy[i]?.value ?? 0,
    stress: history.stress[i]?.value ?? 0,
  }));

  return merged;
}

function useLLMHistory() {
  const [series, setSeries] = useState<HistoryPoint[]>([]);
  useEffect(() => {
    const load = async () => setSeries(await fetchHistory("llm_latency", 60));
    load();
    const id = setInterval(load, 60_000);
    return () => clearInterval(id);
  }, []);
  return series;
}

// ── Page ──────────────────────────────────────────────────────────────────────
export default function MonitoringPage() {
  const { data, loading, lastRefresh, refresh } = useMetrics();
  const brainHistory = useBrainHistory();
  const llmHistory   = useLLMHistory();

  const { brain_state: bs, llm, infra, http_endpoints, alerts } = data;

  const refreshedAt = lastRefresh
    ? new Date(lastRefresh).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : "—";

  // Bar chart data for HTTP endpoints
  const httpBar = http_endpoints
    .slice(0, 8)
    .map((e) => ({ name: `${e.method} ${e.path}`, count: e.count, status: e.status }));

  return (
    <main className="min-h-screen bg-zinc-950 text-white">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800">
        <div>
          <h1 className="text-lg font-bold tracking-tight">System Monitor</h1>
          <p className="text-zinc-600 text-xs mt-0.5">Updated {refreshedAt} · 15s auto-refresh</p>
        </div>
        <button
          onClick={refresh}
          className="text-xs px-3 py-1.5 rounded-lg border border-zinc-700 text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors"
        >
          Refresh
        </button>
      </header>

      <div className="max-w-7xl mx-auto px-6 py-8 space-y-10">

        {/* ── Brain State ─────────────────────────────────────────────────── */}
        <Section title="Brain State">
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">

            {/* Gauges */}
            <Card className="flex justify-around items-center py-6 lg:col-span-1">
              <ArcGauge value={bs.focus}  label="Focus"  color={C.focus}  />
              <ArcGauge value={bs.energy} label="Energy" color={C.energy} />
              <ArcGauge value={bs.stress} label="Stress" color={C.stress}
                max={10}
              />
            </Card>

            {/* Time series */}
            <Card className="lg:col-span-2">
              <p className="text-xs text-zinc-500 mb-3">Last 3 hours</p>
              {brainHistory.length === 0 ? (
                <div className="h-36 flex items-center justify-center text-zinc-700 text-sm">
                  No history yet — keep the server running
                </div>
              ) : (
                <ResponsiveContainer width="100%" height={140}>
                  <LineChart data={brainHistory} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                    <XAxis dataKey="ts" hide />
                    <YAxis domain={[0, 10]} tick={{ fontSize: 10, fill: "#52525b" }} />
                    <Tooltip content={<ChartTip />} />
                    <Line dataKey="focus"  stroke={C.focus}  dot={false} strokeWidth={2} name="Focus" />
                    <Line dataKey="energy" stroke={C.energy} dot={false} strokeWidth={2} name="Energy" />
                    <Line dataKey="stress" stroke={C.stress} dot={false} strokeWidth={2} name="Stress" />
                  </LineChart>
                </ResponsiveContainer>
              )}
              <div className="flex gap-4 mt-2">
                {[["Focus", C.focus], ["Energy", C.energy], ["Stress", C.stress]].map(([l, c]) => (
                  <div key={l} className="flex items-center gap-1.5">
                    <div className="w-2.5 h-0.5" style={{ background: c }} />
                    <span className="text-xs text-zinc-500">{l}</span>
                  </div>
                ))}
              </div>
            </Card>
          </div>
        </Section>

        {/* ── AI / LLM ────────────────────────────────────────────────────── */}
        <Section title="AI / LLM">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
            <StatTile label="Requests (24h)" value={llm.requests_24h} color={C.purple} />
            <StatTile label="p95 Latency"    value={`${llm.latency_p95}s`}
              color={llm.latency_p95 > 10 ? "#ef4444" : llm.latency_p95 > 5 ? "#f97316" : "#22c55e"}
              sub="last 10 min window"
            />
            <StatTile label="Errors (1h)"    value={llm.errors_1h}
              color={llm.errors_1h > 0 ? "#ef4444" : "#22c55e"}
            />
            <StatTile label="Model tier"     value="Ollama" sub="llama3.2:3b — local" color={C.zinc} />
          </div>

          <Card>
            <p className="text-xs text-zinc-500 mb-3">p95 Latency — last 60 min</p>
            {llmHistory.length === 0 ? (
              <div className="h-24 flex items-center justify-center text-zinc-700 text-sm">
                Make a few AI requests to see latency data
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={100}>
                <LineChart data={llmHistory} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis dataKey="ts" hide />
                  <YAxis tick={{ fontSize: 10, fill: "#52525b" }} />
                  <Tooltip content={<ChartTip unit="s" />} />
                  <Line dataKey="value" stroke={C.purple} dot={false} strokeWidth={2} name="Latency" />
                </LineChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Section>

        {/* ── HTTP ────────────────────────────────────────────────────────── */}
        <Section title="HTTP Endpoints">
          <Card>
            <p className="text-xs text-zinc-500 mb-4">Requests in last hour — top 8 routes</p>
            {httpBar.length === 0 ? (
              <div className="h-24 flex items-center justify-center text-zinc-700 text-sm">
                No requests recorded yet
              </div>
            ) : (
              <ResponsiveContainer width="100%" height={180}>
                <BarChart data={httpBar} layout="vertical"
                  margin={{ top: 0, right: 20, bottom: 0, left: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10, fill: "#52525b" }} />
                  <YAxis dataKey="name" type="category" width={180}
                    tick={{ fontSize: 10, fill: "#a1a1aa" }} />
                  <Tooltip
                    contentStyle={{ background: "#18181b", border: "1px solid #3f3f46", borderRadius: 8, fontSize: 12 }}
                    labelStyle={{ color: "#71717a" }}
                  />
                  <Bar dataKey="count" fill={C.focus} radius={[0, 4, 4, 0]} name="Requests" />
                </BarChart>
              </ResponsiveContainer>
            )}
          </Card>
        </Section>

        {/* ── Infrastructure ───────────────────────────────────────────────── */}
        <Section title="Infrastructure">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <Card>
              <p className="text-xs text-zinc-500 mb-3">Services</p>
              <div className="flex flex-wrap gap-2">
                <ServiceBadge label="Redis"      alive={infra.redis}  />
                <ServiceBadge label="Ollama"     alive={infra.ollama} />
                <ServiceBadge label="MQTT"       alive={infra.mqtt}   />
                <ServiceBadge label="FastAPI"    alive={true}         />
                <ServiceBadge label="Prometheus" alive={true}         />
              </div>
            </Card>

            <Card>
              <DeadManGauge seconds={infra.deadman_s} />
            </Card>
          </div>
        </Section>

        {/* ── Alerts ──────────────────────────────────────────────────────── */}
        {alerts.length > 0 && (
          <Section title="Alerts">
            <Card>
              <div className="divide-y divide-zinc-800">
                {alerts.map((a) => (
                  <div key={a.name} className="flex justify-between py-2.5 text-sm">
                    <span className="text-zinc-300 font-mono">{a.name}</span>
                    <span className={`font-semibold ${a.total > 0 ? "text-orange-400" : "text-zinc-600"}`}>
                      {a.total} fires
                    </span>
                  </div>
                ))}
              </div>
            </Card>
          </Section>
        )}

      </div>
    </main>
  );
}
