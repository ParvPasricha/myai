"use client";

const EMOJI: Record<string, string> = {
  happy:     "😊",
  focused:   "🎯",
  neutral:   "😐",
  tired:     "😴",
  sad:       "😔",
  angry:     "😤",
  surprised: "😲",
};

export function EmotionBadge({ emotion }: { emotion: string }) {
  const emoji = EMOJI[emotion] ?? "🤔";
  return (
    <span className="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-zinc-800 border border-zinc-700 text-sm">
      {emoji}
      <span className="text-zinc-300 capitalize text-xs">{emotion}</span>
    </span>
  );
}
