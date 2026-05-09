"use client";

interface Props {
  topic: string;
  quizStatus: string;
}

export function TopicCard({ topic, quizStatus }: Props) {
  const quizDone = quizStatus === "completed";

  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider mb-1">
            Today&apos;s Research
          </p>
          <p className="text-base font-semibold leading-snug">{topic}</p>
        </div>
        <span
          className={`shrink-0 mt-1 px-2.5 py-1 rounded-full text-xs font-medium ${
            quizDone
              ? "bg-green-900/40 text-green-400 border border-green-800"
              : "bg-amber-900/40 text-amber-400 border border-amber-800"
          }`}
        >
          {quizDone ? "✓ Quiz done" : "Quiz pending"}
        </span>
      </div>
    </div>
  );
}
