"use client";

interface Props {
  activity: string;
  location: string;
  micStage: string;
}

const MIC_LABELS: Record<string, string> = {
  push_to_talk: "Push-to-talk",
  wake_phrase: "Wake phrase",
  passive: "Passive",
  voip: "Always-on",
};

export function ActivityCard({ activity, location, micStage }: Props) {
  return (
    <div className="rounded-2xl bg-zinc-900 border border-zinc-800 p-5 flex flex-col gap-4">
      <p className="text-xs font-semibold text-zinc-500 uppercase tracking-wider">
        Right Now
      </p>

      <div>
        <p className="text-xs text-zinc-500 mb-0.5">Activity</p>
        <p className="text-lg font-semibold capitalize">{activity}</p>
      </div>

      <div>
        <p className="text-xs text-zinc-500 mb-0.5">Location</p>
        <div className="flex items-center gap-2">
          <span className="text-base">📍</span>
          <p className="text-base font-medium capitalize">{location}</p>
        </div>
      </div>

      <div>
        <p className="text-xs text-zinc-500 mb-0.5">Listening</p>
        <span className="inline-block px-2 py-0.5 rounded-full bg-zinc-800 text-zinc-300 text-xs">
          {MIC_LABELS[micStage] ?? micStage}
        </span>
      </div>
    </div>
  );
}
