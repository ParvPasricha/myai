"use client";
import { useSearchParams, useRouter } from "next/navigation";
import { Suspense } from "react";
import { useDashboard } from "@/lib/useDashboard";
import { BrainStateCard } from "@/components/BrainStateCard";
import { ActivityCard } from "@/components/ActivityCard";
import { TopicCard } from "@/components/TopicCard";
import { ConnectionDot } from "@/components/ConnectionDot";
import { EmotionBadge } from "@/components/EmotionBadge";

function Dashboard() {
  const params = useSearchParams();
  const token = params.get("token") ?? undefined;
  const { state, connected } = useDashboard(token);

  const updatedAt = new Date(state.last_updated).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
  });

  return (
    <main className="min-h-screen bg-zinc-950 text-white p-4 md:p-8">
      {/* Header */}
      <div className="flex items-center justify-between mb-8 max-w-3xl mx-auto">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">whatsparvdoing</h1>
          <p className="text-zinc-500 text-sm mt-0.5">Updated {updatedAt}</p>
        </div>
        <div className="flex items-center gap-3">
          {state.emotion && <EmotionBadge emotion={state.emotion} />}
          <ConnectionDot connected={connected} />
        </div>
      </div>

      {/* Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 max-w-3xl mx-auto">
        <BrainStateCard
          focus={state.focus_score}
          energy={state.energy_score}
          stress={state.stress_score}
          deepWork={state.deep_work}
        />
        <ActivityCard
          activity={state.current_activity}
          location={state.location}
          micStage={state.mic_stage}
        />
        {state.today_topic && (
          <div className="md:col-span-2">
            <TopicCard topic={state.today_topic} quizStatus={state.quiz_status} />
          </div>
        )}
      </div>

      <p className="text-center text-zinc-700 text-xs mt-12">
        PARV-AI · Private feed · Read-only
      </p>
    </main>
  );
}

export default function Page() {
  return (
    <Suspense>
      <Dashboard />
    </Suspense>
  );
}
