"use client";

import { useState, useRef, useCallback, useEffect } from "react";
import { useIntelligence, GraphNode, GraphEdge } from "@/lib/useIntelligence";

// ── colour + shape per node type ─────────────────────────────────────────────
const NODE_STYLE: Record<string, { fill: string; stroke: string; label: string }> = {
  file:     { fill: "#1d4ed8", stroke: "#3b82f6", label: "File" },
  service:  { fill: "#166534", stroke: "#22c55e", label: "Service" },
  memory:   { fill: "#6b21a8", stroke: "#a855f7", label: "Memory" },
  decision: { fill: "#92400e", stroke: "#f59e0b", label: "Decision" },
};

const DEAD_SERVICE = { fill: "#450a0a", stroke: "#ef4444" };

// ── layout helpers ────────────────────────────────────────────────────────────
interface Pos { x: number; y: number }

function layoutNodes(nodes: GraphNode[]): Map<string, Pos> {
  const pos = new Map<string, Pos>();
  const services  = nodes.filter((n) => n.type === "service");
  const files     = nodes.filter((n) => n.type === "file");
  const memories  = nodes.filter((n) => n.type === "memory");
  const decisions = nodes.filter((n) => n.type === "decision");

  const W = 1400;

  // Services — top row
  services.forEach((n, i) => {
    pos.set(n.id, { x: 120 + i * 210, y: 80 });
  });

  // Files — right column grid (3 wide)
  const FILE_COLS = 4;
  files.forEach((n, i) => {
    pos.set(n.id, {
      x: 700 + (i % FILE_COLS) * 140,
      y: 200 + Math.floor(i / FILE_COLS) * 80,
    });
  });

  // Memory nodes — left column grid
  const MEM_COLS = 2;
  memories.forEach((n, i) => {
    pos.set(n.id, {
      x: 100 + (i % MEM_COLS) * 200,
      y: 200 + Math.floor(i / MEM_COLS) * 100,
    });
  });

  // Decisions — bottom row
  decisions.forEach((n, i) => {
    const total = decisions.length;
    pos.set(n.id, {
      x: (W / (total + 1)) * (i + 1),
      y: 720,
    });
  });

  return pos;
}

// ── SVG edge (quadratic bezier) ───────────────────────────────────────────────
function Edge({
  from, to, color = "#374151",
}: {
  from: Pos; to: Pos; color?: string;
}) {
  const mx = (from.x + to.x) / 2;
  const my = (from.y + to.y) / 2 - 30;
  return (
    <path
      d={`M${from.x},${from.y} Q${mx},${my} ${to.x},${to.y}`}
      fill="none"
      stroke={color}
      strokeWidth={1}
      strokeOpacity={0.35}
      markerEnd="url(#arrow)"
    />
  );
}

// ── Node shape ────────────────────────────────────────────────────────────────
function Node({
  node, pos, selected, onClick,
}: {
  node: GraphNode;
  pos: Pos;
  selected: boolean;
  onClick: () => void;
}) {
  const base = NODE_STYLE[node.type] ?? NODE_STYLE.file;
  const style =
    node.type === "service" && node.alive === false ? DEAD_SERVICE : base;

  const R = node.type === "service" ? 24 : 18;
  const isService = node.type === "service";

  return (
    <g
      transform={`translate(${pos.x},${pos.y})`}
      style={{ cursor: "pointer" }}
      onClick={onClick}
    >
      {isService ? (
        // Hexagon for services
        <polygon
          points={hexPoints(R)}
          fill={style.fill}
          stroke={selected ? "#fff" : style.stroke}
          strokeWidth={selected ? 2.5 : 1.5}
        />
      ) : (
        <circle
          r={R}
          fill={style.fill}
          stroke={selected ? "#fff" : style.stroke}
          strokeWidth={selected ? 2.5 : 1.5}
        />
      )}
      <text
        textAnchor="middle"
        dy={R + 14}
        fontSize={9}
        fill="#d1d5db"
        style={{ pointerEvents: "none", userSelect: "none" }}
      >
        {truncate(node.label, 16)}
      </text>
      {node.type === "service" && (
        <circle
          cx={R - 4}
          cy={-(R - 4)}
          r={5}
          fill={node.alive ? "#22c55e" : "#ef4444"}
        />
      )}
    </g>
  );
}

function hexPoints(r: number): string {
  return Array.from({ length: 6 }, (_, i) => {
    const a = (Math.PI / 3) * i - Math.PI / 6;
    return `${r * Math.cos(a)},${r * Math.sin(a)}`;
  }).join(" ");
}

function truncate(s: string, n: number) {
  return s.length > n ? s.slice(0, n - 1) + "…" : s;
}

// ── Detail panel ──────────────────────────────────────────────────────────────
function DetailPanel({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const base = NODE_STYLE[node.type] ?? NODE_STYLE.file;
  return (
    <div className="absolute right-4 top-20 w-72 bg-zinc-900 border border-zinc-700 rounded-xl p-4 shadow-2xl z-10">
      <div className="flex items-center justify-between mb-3">
        <span
          className="text-xs font-semibold px-2 py-0.5 rounded-full"
          style={{ background: base.fill, color: "#fff" }}
        >
          {NODE_STYLE[node.type]?.label ?? node.type}
        </span>
        <button
          onClick={onClose}
          className="text-zinc-500 hover:text-white text-lg leading-none"
        >
          ×
        </button>
      </div>

      <p className="text-white font-medium text-sm mb-3 break-all">{node.label}</p>

      {node.path && (
        <Row label="Path" value={node.path} />
      )}
      {node.size !== undefined && (
        <Row label="Lines" value={String(node.size)} />
      )}
      {node.lang && (
        <Row label="Language" value={node.lang} />
      )}
      {node.port !== undefined && (
        <Row label="Port" value={String(node.port)} />
      )}
      {node.alive !== undefined && (
        <Row
          label="Status"
          value={node.alive ? "Running" : "Down"}
          valueClass={node.alive ? "text-green-400" : "text-red-400"}
        />
      )}
      {node.domain && (
        <Row label="Domain" value={node.domain} />
      )}

      {node.functions && node.functions.length > 0 && (
        <div className="mt-3">
          <p className="text-zinc-500 text-xs mb-1">Functions</p>
          <div className="flex flex-wrap gap-1">
            {node.functions.slice(0, 12).map((f) => (
              <span
                key={f}
                className="text-xs bg-zinc-800 text-zinc-300 px-1.5 py-0.5 rounded"
              >
                {f}
              </span>
            ))}
          </div>
        </div>
      )}

      {node.imports && node.imports.length > 0 && (
        <div className="mt-3">
          <p className="text-zinc-500 text-xs mb-1">Imports</p>
          <div className="flex flex-wrap gap-1">
            {node.imports.slice(0, 10).map((imp) => (
              <span
                key={imp}
                className="text-xs bg-zinc-800 text-blue-300 px-1.5 py-0.5 rounded"
              >
                {imp}
              </span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function Row({
  label, value, valueClass = "text-zinc-300",
}: {
  label: string; value: string; valueClass?: string;
}) {
  return (
    <div className="flex justify-between text-xs mb-1.5">
      <span className="text-zinc-500">{label}</span>
      <span className={valueClass}>{value}</span>
    </div>
  );
}

// ── Legend ────────────────────────────────────────────────────────────────────
function Legend() {
  return (
    <div className="flex gap-4 items-center">
      {Object.entries(NODE_STYLE).map(([type, s]) => (
        <div key={type} className="flex items-center gap-1.5">
          <div
            className="w-3 h-3 rounded-full"
            style={{ background: s.stroke }}
          />
          <span className="text-zinc-400 text-xs">{s.label}</span>
        </div>
      ))}
      <div className="flex items-center gap-1.5">
        <div className="w-3 h-3 rounded-full bg-red-500" />
        <span className="text-zinc-400 text-xs">Service down</span>
      </div>
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────
export default function IntelligencePage() {
  const { graph, connected } = useIntelligence();
  const [selected, setSelected] = useState<GraphNode | null>(null);
  const [filter, setFilter] = useState<Set<string>>(
    new Set(["file", "service", "memory", "decision"])
  );

  // Pan / zoom state
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [zoom, setZoom] = useState(1.0);
  const dragging = useRef(false);
  const dragStart = useRef({ x: 0, y: 0 });
  const panStart = useRef({ x: 0, y: 0 });

  const visibleNodes = graph.nodes.filter((n) => filter.has(n.type));
  const posMap = layoutNodes(visibleNodes);

  // Edge lookup
  const nodeSet = new Set(visibleNodes.map((n) => n.id));
  const visibleEdges = graph.edges.filter(
    (e) => nodeSet.has(e.from) && nodeSet.has(e.to)
  );

  const onWheel = useCallback((e: React.WheelEvent) => {
    e.preventDefault();
    setZoom((z) => Math.min(2, Math.max(0.3, z - e.deltaY * 0.001)));
  }, []);

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    dragging.current = true;
    dragStart.current = { x: e.clientX, y: e.clientY };
    panStart.current = { ...pan };
  }, [pan]);

  const onMouseMove = useCallback((e: React.MouseEvent) => {
    if (!dragging.current) return;
    setPan({
      x: panStart.current.x + (e.clientX - dragStart.current.x),
      y: panStart.current.y + (e.clientY - dragStart.current.y),
    });
  }, []);

  const onMouseUp = useCallback(() => { dragging.current = false; }, []);

  const toggleFilter = (type: string) => {
    setFilter((prev) => {
      const next = new Set(prev);
      next.has(type) ? next.delete(type) : next.add(type);
      return next;
    });
  };

  const stats = {
    files:    graph.nodes.filter((n) => n.type === "file").length,
    services: graph.nodes.filter((n) => n.type === "service").length,
    alive:    graph.nodes.filter((n) => n.type === "service" && n.alive).length,
    edges:    graph.edges.length,
  };

  const lastUpdated = graph.last_updated
    ? new Date(graph.last_updated * 1000).toLocaleTimeString([], {
        hour: "2-digit", minute: "2-digit",
      })
    : "—";

  return (
    <main className="min-h-screen bg-zinc-950 text-white flex flex-col">
      {/* Header */}
      <header className="flex items-center justify-between px-6 py-4 border-b border-zinc-800 flex-shrink-0">
        <div>
          <h1 className="text-lg font-bold tracking-tight">
            Intelligence Layer
          </h1>
          <p className="text-zinc-500 text-xs mt-0.5">
            Live code graph · memory · services · decisions
          </p>
        </div>

        <div className="flex items-center gap-6">
          <Legend />
          <div className="flex items-center gap-2">
            <div
              className={`w-2 h-2 rounded-full ${
                connected ? "bg-green-400" : "bg-red-500"
              }`}
            />
            <span className="text-xs text-zinc-400">
              {connected ? "live" : "reconnecting…"}
            </span>
          </div>
        </div>
      </header>

      {/* Stats bar */}
      <div className="flex gap-6 px-6 py-2 bg-zinc-900 border-b border-zinc-800 flex-shrink-0">
        {[
          { label: "Files", value: stats.files, color: "#3b82f6" },
          { label: "Services", value: `${stats.alive}/${stats.services}`, color: "#22c55e" },
          { label: "Edges", value: stats.edges, color: "#6b7280" },
          { label: "Last scan", value: lastUpdated, color: "#a855f7" },
        ].map((s) => (
          <div key={s.label} className="text-xs">
            <span className="text-zinc-500">{s.label} </span>
            <span className="font-semibold" style={{ color: s.color }}>
              {s.value}
            </span>
          </div>
        ))}

        {/* Filter toggles */}
        <div className="ml-auto flex gap-2">
          {Object.entries(NODE_STYLE).map(([type, s]) => (
            <button
              key={type}
              onClick={() => toggleFilter(type)}
              className="text-xs px-2 py-0.5 rounded-full border transition-opacity"
              style={{
                borderColor: s.stroke,
                color: filter.has(type) ? s.stroke : "#6b7280",
                opacity: filter.has(type) ? 1 : 0.4,
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {/* Graph canvas */}
      <div
        className="flex-1 relative overflow-hidden"
        onWheel={onWheel}
        onMouseDown={onMouseDown}
        onMouseMove={onMouseMove}
        onMouseUp={onMouseUp}
        onMouseLeave={onMouseUp}
        style={{ cursor: dragging.current ? "grabbing" : "grab" }}
      >
        <svg
          width="100%"
          height="100%"
          style={{
            transform: `translate(${pan.x}px, ${pan.y}px) scale(${zoom})`,
            transformOrigin: "0 0",
          }}
        >
          <defs>
            <marker
              id="arrow"
              markerWidth="6"
              markerHeight="6"
              refX="5"
              refY="3"
              orient="auto"
            >
              <path d="M0,0 L0,6 L6,3 z" fill="#374151" />
            </marker>
          </defs>

          {/* Edges */}
          {visibleEdges.map((e, i) => {
            const from = posMap.get(e.from);
            const to   = posMap.get(e.to);
            if (!from || !to) return null;
            return (
              <Edge
                key={i}
                from={from}
                to={to}
                color={e.type === "imports" ? "#1e40af" : "#374151"}
              />
            );
          })}

          {/* Nodes */}
          {visibleNodes.map((n) => {
            const p = posMap.get(n.id);
            if (!p) return null;
            return (
              <Node
                key={n.id}
                node={n}
                pos={p}
                selected={selected?.id === n.id}
                onClick={() =>
                  setSelected((prev) => (prev?.id === n.id ? null : n))
                }
              />
            );
          })}
        </svg>

        {/* Empty state */}
        {visibleNodes.length === 0 && (
          <div className="absolute inset-0 flex flex-col items-center justify-center gap-3">
            <div className="w-12 h-12 rounded-full border-2 border-zinc-700 border-t-purple-500 animate-spin" />
            <p className="text-zinc-500 text-sm">
              {connected
                ? "Overwatcher scanning project…"
                : "Connecting to intelligence layer…"}
            </p>
          </div>
        )}

        {/* Zoom hint */}
        <div className="absolute bottom-4 left-4 text-zinc-700 text-xs select-none">
          Scroll to zoom · Drag to pan · Click node for details
        </div>

        {/* Zoom level */}
        <div className="absolute bottom-4 right-4 text-zinc-600 text-xs select-none">
          {Math.round(zoom * 100)}%
        </div>

        {/* Detail panel */}
        {selected && (
          <DetailPanel node={selected} onClose={() => setSelected(null)} />
        )}
      </div>
    </main>
  );
}
