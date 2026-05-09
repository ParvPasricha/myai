"use client";

interface Props {
  focus: number;
  energy: number;
  stress: number;
  deepWork: boolean;
}

function Ring({ label, value, color }: { label: string; value: number; color: string }) {
  const pct = (value / 10) * 100;
  const r = 28;
  const circ = 2 * Math.PI * r;
  const offset = circ - (pct / 100) * circ;

  return (
    <div className="flex flex-col items-center gap-1.5">
      <div className="relative w-16 h-16">
        <svg className="w-full h-full -rotate-90" viewBox="0 0 64 64">
          <circle cx="32" cy="32" r={r} fill="none" stroke="#27272a" strokeWidth="6" />
          <circle
            cx="32" cy="32" r={r} fill="none"
            stroke={color} strokeWidth="6"
            strokeLinecap="round"
            strokeDasharray={circ}
            strokeDashoffset={offset}
            style={{ transition: "stroke-dashoffset 0.6s ease" }}
          />
        </svg>
        <span className="absolute inset-0 flex items-center justify-center text-lg font-bold">
          {value}
        </span>
      </div>
      <span className="text-xs text-zinc-400">{label}</span>
    </div>
  );
}

export function BrainStateCard({ focus, energy, stress, deepWork }: Props) {
  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-5">
      <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-4">
        Brain State
      </p>
      <div className="flex justify-around">
        <Ring label="Focus"  value={focus}  color="#3b82f6" />
        <Ring label="Energy" value={energy} color="#22c55e" />
        <Ring label="Stress" value={stress} color="#f97316" />
      </div>
      {deepWork && (
        <div className="mt-4 flex items-center gap-2 text-purple-400 text-sm">
          <span className="w-2 h-2 rounded-full bg-purple-400 animate-pulse" />
          Deep Work Mode
        </div>
      )}
    </div>
  );
}
