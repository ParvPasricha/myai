"use client";

export function ConnectionDot({ connected }: { connected: boolean }) {
  return (
    <div className="flex items-center gap-1.5 text-xs text-zinc-500">
      <span
        className={`w-2 h-2 rounded-full ${
          connected ? "bg-green-500 animate-pulse" : "bg-zinc-600"
        }`}
      />
      {connected ? "Live" : "Offline"}
    </div>
  );
}
