"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

type CardType = "news" | "study" | "code" | "quiz" | "explore" | "challenge";
type Mode = "feed" | "teach" | "work" | "quiz" | "profile";

interface FeedCard {
  type: CardType;
  domain: string;
  title: string;
  description: string;
  topic: string;
  difficulty: "beginner" | "intermediate" | "advanced";
}

interface QuizQuestion {
  id: number;
  question: string;
  options: string[];
}

interface QuizResult {
  questionId: number;
  selected: string;
  correct: boolean;
  correctAnswer: string;
  explanation: string;
}

interface ProfileData {
  total_conversations: number;
  total_decisions: number;
  top_domains: { domain: string; count: number }[];
  detected_habits: string[];
  recent_decisions: { content: string; domain: string; ts: number }[];
  recent_topics: string[];
}

interface TeachPlan {
  title: string;
  estimated_minutes: number;
  sections: { title: string; key_points: string[]; has_code: boolean }[];
  prerequisites: string[];
  what_you_will_build: string;
}

// ── Auth token (dev) ──────────────────────────────────────────────────────────

async function getToken(): Promise<string> {
  const cached = sessionStorage.getItem("parv_token");
  if (cached) return cached;
  const r = await fetch(`${API}/auth/token`, { method: "POST" });
  const j = await r.json();
  const tok = j.access_token;
  sessionStorage.setItem("parv_token", tok);
  return tok;
}

function authHeaders() {
  const tok = sessionStorage.getItem("parv_token") ?? "";
  return { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" };
}

// ── Card type meta ────────────────────────────────────────────────────────────

const CARD_META: Record<CardType, { icon: string; color: string; label: string }> = {
  news:      { icon: "◈", color: "#3b82f6", label: "News"      },
  study:     { icon: "◉", color: "#a855f7", label: "Study"     },
  code:      { icon: "◧", color: "#22c55e", label: "Code"      },
  quiz:      { icon: "◎", color: "#f59e0b", label: "Quiz"      },
  explore:   { icon: "◐", color: "#06b6d4", label: "Explore"   },
  challenge: { icon: "◈", color: "#f97316", label: "Challenge" },
};

const DIFF_COLOR = { beginner: "#22c55e", intermediate: "#f59e0b", advanced: "#ef4444" };
const DOMAIN_COLOR: Record<string, string> = {
  code: "#3b82f6", physics: "#06b6d4", maths: "#a855f7",
  business: "#22c55e", editing: "#f97316", personal: "#ec4899", general: "#71717a",
};

// ── Streaming hook ────────────────────────────────────────────────────────────

function useStream() {
  const [text, setText] = useState("");
  const [streaming, setStreaming] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  const start = useCallback(async (
    prompt: string,
    mode: string,
    topic?: string,
    context?: string,
  ) => {
    abortRef.current?.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    setText("");
    setStreaming(true);

    try {
      const tok = await getToken();
      const r = await fetch(`${API}/assistant/stream`, {
        method: "POST",
        headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
        body: JSON.stringify({ prompt, mode, topic, context }),
        signal: ctrl.signal,
      });

      const reader = r.body!.getReader();
      const dec = new TextDecoder();
      let buf = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const payload = line.slice(6).trim();
          if (payload === "[DONE]") { setStreaming(false); return; }
          try {
            const j = JSON.parse(payload);
            if (j.token) setText((p) => p + j.token);
          } catch {}
        }
      }
    } catch (e: any) {
      if (e.name !== "AbortError") setText((p) => p + "\n\n[Stream error]");
    }
    setStreaming(false);
  }, []);

  const stop = useCallback(() => {
    abortRef.current?.abort();
    setStreaming(false);
  }, []);

  return { text, setText, streaming, start, stop };
}

// ── Components ────────────────────────────────────────────────────────────────

function Card_({
  card, onClick,
}: { card: FeedCard; onClick: () => void }) {
  const meta = CARD_META[card.type] ?? CARD_META.explore;
  const dc   = DOMAIN_COLOR[card.domain] ?? "#71717a";
  return (
    <button
      onClick={onClick}
      className="text-left bg-zinc-900 border border-zinc-800 rounded-xl p-4
                 hover:border-zinc-600 hover:bg-zinc-800/60
                 transition-all duration-150 group w-full"
    >
      <div className="flex items-center justify-between mb-2.5">
        <div className="flex items-center gap-2">
          <span style={{ color: meta.color }} className="text-base">{meta.icon}</span>
          <span className="text-xs font-semibold tracking-wide"
                style={{ color: meta.color }}>{meta.label}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <span className="text-xs px-1.5 py-0.5 rounded"
                style={{ background: dc + "22", color: dc }}>{card.domain}</span>
          <span className="text-xs px-1.5 py-0.5 rounded bg-zinc-800"
                style={{ color: DIFF_COLOR[card.difficulty] }}>{card.difficulty}</span>
        </div>
      </div>
      <p className="text-white font-semibold text-sm leading-snug mb-1.5
                    group-hover:text-blue-200 transition-colors">
        {card.title}
      </p>
      <p className="text-zinc-500 text-xs leading-relaxed">{card.description}</p>
    </button>
  );
}

function StreamOutput({ text, streaming }: { text: string; streaming: boolean }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (ref.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [text]);

  return (
    <div ref={ref}
      className="flex-1 overflow-y-auto p-4 font-mono text-sm text-zinc-200
                 leading-relaxed whitespace-pre-wrap min-h-0">
      {text || (
        <span className="text-zinc-600 italic">
          Response will appear here…
        </span>
      )}
      {streaming && (
        <span className="inline-block w-2 h-4 bg-blue-400 ml-0.5 animate-pulse align-text-bottom" />
      )}
    </div>
  );
}

function QuizPanel({
  quizId, questions, onDone,
}: {
  quizId: string;
  questions: QuizQuestion[];
  onDone: (score: number, total: number) => void;
}) {
  const [idx, setIdx]       = useState(0);
  const [results, setResults] = useState<QuizResult[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [checking, setChecking] = useState(false);
  const [result, setResult]   = useState<QuizResult | null>(null);

  const q = questions[idx];
  if (!q) return null;

  const check = async (ans: string) => {
    if (checking || result) return;
    setSelected(ans);
    setChecking(true);
    const tok = await getToken();
    const r = await fetch(`${API}/assistant/quiz/check`, {
      method: "POST",
      headers: { Authorization: `Bearer ${tok}`, "Content-Type": "application/json" },
      body: JSON.stringify({ quiz_id: quizId, question_id: q.id, answer: ans }),
    });
    const data = await r.json();
    const res: QuizResult = {
      questionId: q.id, selected: ans,
      correct: data.correct, correctAnswer: data.correct_answer,
      explanation: data.explanation,
    };
    setResult(res);
    setResults((p) => [...p, res]);
    setChecking(false);
  };

  const next = () => {
    if (idx + 1 >= questions.length) {
      const score = results.filter((r) => r.correct).length + (result?.correct ? 0 : 0);
      const finalScore = [...results, result!].filter(Boolean).filter((r) => r.correct).length;
      onDone(finalScore, questions.length);
    } else {
      setIdx((i) => i + 1);
      setSelected(null);
      setResult(null);
    }
  };

  return (
    <div className="flex flex-col gap-4 p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs text-zinc-500">
          Question {idx + 1} of {questions.length}
        </span>
        <div className="flex gap-1">
          {questions.map((_, i) => (
            <div key={i} className={`w-1.5 h-1.5 rounded-full ${
              i < idx ? "bg-green-500" : i === idx ? "bg-blue-400" : "bg-zinc-700"
            }`} />
          ))}
        </div>
      </div>

      <p className="text-white font-medium leading-snug">{q.question}</p>

      <div className="flex flex-col gap-2">
        {q.options.map((opt) => {
          const letter = opt[0];
          const isSelected = selected === letter;
          const isCorrect  = result?.correctAnswer === letter;
          const isWrong    = result && isSelected && !result.correct;

          return (
            <button
              key={opt}
              onClick={() => check(letter)}
              disabled={!!result || checking}
              className={`text-left px-4 py-3 rounded-lg border text-sm transition-all ${
                isCorrect && result
                  ? "border-green-500 bg-green-950 text-green-300"
                  : isWrong
                  ? "border-red-500 bg-red-950 text-red-300"
                  : isSelected
                  ? "border-blue-500 bg-blue-950 text-blue-200"
                  : "border-zinc-700 bg-zinc-800/50 text-zinc-300 hover:border-zinc-500"
              }`}
            >
              {opt}
            </button>
          );
        })}
      </div>

      {result && (
        <div className={`rounded-lg p-3 text-sm border ${
          result.correct
            ? "bg-green-950 border-green-800 text-green-300"
            : "bg-red-950 border-red-800 text-red-300"
        }`}>
          <p className="font-semibold mb-1">{result.correct ? "Correct!" : `Wrong — answer is ${result.correctAnswer}`}</p>
          <p className="text-xs opacity-80 leading-relaxed">{result.explanation}</p>
        </div>
      )}

      {result && (
        <button
          onClick={next}
          className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500
                     text-white text-sm font-semibold transition-colors"
        >
          {idx + 1 >= questions.length ? "See Results" : "Next Question →"}
        </button>
      )}
    </div>
  );
}

function ProfilePanel({ profile }: { profile: ProfileData }) {
  return (
    <div className="p-4 space-y-5 overflow-y-auto flex-1">
      {/* Stats */}
      <div className="grid grid-cols-2 gap-3">
        {[
          { label: "Conversations learned from", value: profile.total_conversations },
          { label: "Decisions logged", value: profile.total_decisions },
        ].map((s) => (
          <div key={s.label} className="bg-zinc-800/60 rounded-lg p-3">
            <p className="text-xs text-zinc-500 mb-1">{s.label}</p>
            <p className="text-xl font-bold text-white">{s.value}</p>
          </div>
        ))}
      </div>

      {/* Domain breakdown */}
      {profile.top_domains.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 mb-2 uppercase tracking-wider">Your Domains</p>
          <div className="space-y-1.5">
            {profile.top_domains.map(({ domain, count }) => {
              const max = profile.top_domains[0]?.count || 1;
              const dc = DOMAIN_COLOR[domain] ?? "#71717a";
              return (
                <div key={domain} className="flex items-center gap-3">
                  <span className="text-xs w-16 text-zinc-400 capitalize">{domain}</span>
                  <div className="flex-1 h-1.5 bg-zinc-800 rounded-full overflow-hidden">
                    <div className="h-full rounded-full transition-all"
                         style={{ width: `${(count / max) * 100}%`, background: dc }} />
                  </div>
                  <span className="text-xs text-zinc-600 w-6 text-right">{count}</span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Detected habits */}
      {profile.detected_habits.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 mb-2 uppercase tracking-wider">Detected Habits</p>
          <div className="space-y-1.5">
            {profile.detected_habits.map((h, i) => (
              <div key={i} className="text-xs text-zinc-300 bg-zinc-800/60 rounded px-3 py-2
                                      leading-relaxed">
                {h.length > 120 ? h.slice(0, 120) + "…" : h}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent topics */}
      {profile.recent_topics.length > 0 && (
        <div>
          <p className="text-xs text-zinc-500 mb-2 uppercase tracking-wider">Recent Topics</p>
          {profile.recent_topics.map((t, i) => (
            <p key={i} className="text-xs text-zinc-400 mb-1 leading-snug">{t.slice(0, 100)}</p>
          ))}
        </div>
      )}

      {profile.total_conversations === 0 && (
        <div className="text-center py-8">
          <p className="text-zinc-600 text-sm">No memory yet.</p>
          <p className="text-zinc-700 text-xs mt-1">Start chatting — the AI will learn about you.</p>
        </div>
      )}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function AssistantPage() {
  const [cards, setCards]           = useState<FeedCard[]>([]);
  const [loadingFeed, setLoadingFeed] = useState(true);
  const [mode, setMode]             = useState<Mode>("feed");
  const [activeCard, setActiveCard] = useState<FeedCard | null>(null);
  const [prompt, setPrompt]         = useState("");
  const [plan, setPlan]             = useState<TeachPlan | null>(null);
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [quizData, setQuizData]     = useState<{ id: string; questions: QuizQuestion[] } | null>(null);
  const [loadingQuiz, setLoadingQuiz] = useState(false);
  const [quizDone, setQuizDone]     = useState<{ score: number; total: number } | null>(null);
  const [profile, setProfile]       = useState<ProfileData | null>(null);
  const { text, setText, streaming, start, stop } = useStream();
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Init: get token then load feed
  useEffect(() => {
    getToken().then(() => loadFeed());
    loadProfile();
  }, []);

  const loadFeed = async () => {
    setLoadingFeed(true);
    try {
      const r = await fetch(`${API}/assistant/feed`, { headers: authHeaders() });
      const j = await r.json();
      setCards(j.cards ?? []);
    } catch {}
    setLoadingFeed(false);
  };

  const loadProfile = async () => {
    try {
      const r = await fetch(`${API}/assistant/profile`, { headers: authHeaders() });
      setProfile(await r.json());
    } catch {}
  };

  const openCard = async (card: FeedCard) => {
    setActiveCard(card);
    setText("");
    setQuizData(null);
    setQuizDone(null);
    setPlan(null);

    if (card.type === "quiz") {
      setMode("quiz");
      setLoadingQuiz(true);
      try {
        const r = await fetch(`${API}/assistant/quiz/generate`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({ topic: card.topic, n: 5, level: card.difficulty }),
        });
        const j = await r.json();
        setQuizData({ id: j.quiz_id, questions: j.questions });
      } catch {}
      setLoadingQuiz(false);
    } else if (card.type === "study" || card.type === "explore") {
      setMode("teach");
      setLoadingPlan(true);
      try {
        const r = await fetch(`${API}/assistant/teach`, {
          method: "POST",
          headers: authHeaders(),
          body: JSON.stringify({ topic: card.topic, level: card.difficulty }),
        });
        const j = await r.json();
        setPlan(j.plan);
      } catch {}
      setLoadingPlan(false);
      // Auto-start first teaching stream
      start(`Teach me about "${card.topic}" in depth. Start with the core intuition, then go deep.`,
             "teach", card.topic);
    } else {
      setMode("work");
      const modeMap: Record<CardType, string> = {
        code: "work", news: "explain", explore: "teach", challenge: "work",
        study: "teach", quiz: "chat",
      };
      start(
        `Tell me about: "${card.topic}". ${card.description}`,
        modeMap[card.type] ?? "chat",
        card.topic,
      );
    }
  };

  const send = async () => {
    if (!prompt.trim() || streaming) return;
    const p = prompt.trim();
    setPrompt("");
    const m = mode === "feed" ? "chat" : mode === "teach" ? "teach" : "work";
    await start(p, m, activeCard?.topic);
  };

  const modeButtons: { key: Mode; label: string; icon: string }[] = [
    { key: "feed",    label: "Feed",    icon: "⬡" },
    { key: "teach",   label: "Teach",   icon: "◉" },
    { key: "work",    label: "Work",    icon: "◧" },
    { key: "quiz",    label: "Quiz",    icon: "◎" },
    { key: "profile", label: "Profile", icon: "◐" },
  ];

  const rightPanelTitle = () => {
    if (mode === "profile") return "What I know about you";
    if (mode === "quiz" && activeCard) return `Quiz: ${activeCard.title}`;
    if (mode === "teach" && activeCard) return `Teaching: ${activeCard.topic}`;
    if (activeCard) return activeCard.title;
    return "Ask me anything";
  };

  return (
    <main className="h-screen bg-zinc-950 text-white flex flex-col overflow-hidden">
      {/* Header */}
      <header className="flex items-center gap-6 px-6 py-3 border-b border-zinc-800 flex-shrink-0">
        <div>
          <h1 className="text-base font-bold tracking-tight">PARV-AI</h1>
          <p className="text-zinc-600 text-xs">Personal intelligence layer</p>
        </div>

        {/* Mode tabs */}
        <div className="flex gap-1 ml-2">
          {modeButtons.map((b) => (
            <button
              key={b.key}
              onClick={() => {
                setMode(b.key);
                if (b.key === "profile") loadProfile();
                if (b.key === "feed") { setActiveCard(null); setText(""); }
              }}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium
                         transition-colors ${
                mode === b.key
                  ? "bg-zinc-700 text-white"
                  : "text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800/50"
              }`}
            >
              <span>{b.icon}</span>{b.label}
            </button>
          ))}
        </div>

        <button
          onClick={loadFeed}
          disabled={loadingFeed}
          className="ml-auto text-xs px-3 py-1.5 rounded-lg border border-zinc-700
                     text-zinc-400 hover:text-white hover:border-zinc-500 transition-colors
                     disabled:opacity-40"
        >
          {loadingFeed ? "Loading…" : "Refresh feed"}
        </button>
      </header>

      {/* Body */}
      <div className="flex flex-1 min-h-0">

        {/* Left — Feed */}
        <div className="w-96 flex-shrink-0 border-r border-zinc-800 flex flex-col min-h-0">
          <div className="px-4 py-3 border-b border-zinc-800 flex-shrink-0">
            <p className="text-xs font-semibold text-zinc-400 uppercase tracking-wider">
              For You
            </p>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2.5">
            {loadingFeed ? (
              Array.from({ length: 5 }).map((_, i) => (
                <div key={i}
                  className="h-28 bg-zinc-800/40 rounded-xl animate-pulse border border-zinc-800" />
              ))
            ) : cards.length === 0 ? (
              <div className="flex flex-col items-center justify-center h-48 gap-3">
                <div className="w-8 h-8 rounded-full border-2 border-zinc-700 border-t-purple-500 animate-spin" />
                <p className="text-zinc-600 text-sm">Generating your feed…</p>
              </div>
            ) : (
              cards.map((card, i) => (
                <Card_
                  key={i}
                  card={card}
                  onClick={() => openCard(card)}
                />
              ))
            )}

            {/* Quick ask — always at bottom */}
            <div className="pt-2">
              <button
                onClick={() => { setActiveCard(null); setMode("feed"); setText(""); }}
                className="w-full py-2.5 rounded-xl border border-zinc-700 text-zinc-500
                           hover:border-zinc-500 hover:text-zinc-300 text-xs transition-colors"
              >
                + Ask something else
              </button>
            </div>
          </div>
        </div>

        {/* Right — Interactive panel */}
        <div className="flex-1 flex flex-col min-h-0">

          {/* Panel header */}
          <div className="flex items-center gap-3 px-5 py-3 border-b border-zinc-800 flex-shrink-0">
            {activeCard && (
              <span className="text-xs px-2 py-0.5 rounded-full"
                    style={{
                      background: (CARD_META[activeCard.type]?.color ?? "#71717a") + "22",
                      color: CARD_META[activeCard.type]?.color ?? "#71717a",
                    }}>
                {CARD_META[activeCard.type]?.label}
              </span>
            )}
            <p className="text-sm font-semibold text-zinc-200 truncate">
              {rightPanelTitle()}
            </p>
            {streaming && (
              <div className="ml-auto flex items-center gap-1.5">
                <div className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                <span className="text-xs text-green-400">Thinking…</span>
                <button onClick={stop}
                  className="ml-2 text-xs text-zinc-600 hover:text-zinc-400">
                  Stop
                </button>
              </div>
            )}
          </div>

          {/* Panel body */}
          <div className="flex-1 min-h-0 flex flex-col">

            {/* Profile mode */}
            {mode === "profile" && profile && (
              <ProfilePanel profile={profile} />
            )}

            {/* Quiz mode */}
            {mode === "quiz" && (
              <div className="flex-1 overflow-y-auto">
                {loadingQuiz ? (
                  <div className="flex items-center justify-center h-40">
                    <div className="w-8 h-8 border-2 border-zinc-700 border-t-yellow-400
                                    rounded-full animate-spin" />
                  </div>
                ) : quizDone ? (
                  <div className="flex flex-col items-center justify-center gap-4 p-8">
                    <p className="text-5xl font-bold">
                      {quizDone.score}/{quizDone.total}
                    </p>
                    <p className="text-zinc-400">
                      {quizDone.score === quizDone.total
                        ? "Perfect score!"
                        : quizDone.score >= quizDone.total * 0.7
                        ? "Good job — review the ones you missed."
                        : "Keep studying this topic."}
                    </p>
                    <div className="flex gap-3 mt-2">
                      <button
                        onClick={() => { setQuizDone(null); openCard(activeCard!); }}
                        className="px-4 py-2 rounded-lg border border-zinc-700 text-sm
                                   text-zinc-300 hover:border-zinc-500 transition-colors">
                        Try Again
                      </button>
                      <button
                        onClick={() => {
                          setMode("teach");
                          start(`Explain the key concepts in "${activeCard?.topic}" I need to know better.`,
                                "teach", activeCard?.topic);
                        }}
                        className="px-4 py-2 rounded-lg bg-purple-700 hover:bg-purple-600
                                   text-white text-sm font-semibold transition-colors">
                        Deep Dive →
                      </button>
                    </div>
                  </div>
                ) : quizData ? (
                  <QuizPanel
                    quizId={quizData.id}
                    questions={quizData.questions}
                    onDone={(score, total) => setQuizDone({ score, total })}
                  />
                ) : null}
              </div>
            )}

            {/* Teach / Work / Feed modes — streamed text */}
            {mode !== "profile" && mode !== "quiz" && (
              <>
                {/* Teaching plan sidebar */}
                {mode === "teach" && plan && !loadingPlan && (
                  <div className="border-b border-zinc-800 px-5 py-3 bg-zinc-900/50 flex-shrink-0">
                    <p className="text-xs text-zinc-500 mb-2">
                      Outline · ~{plan.estimated_minutes} min
                    </p>
                    <div className="flex gap-2 flex-wrap">
                      {plan.sections?.map((s, i) => (
                        <button
                          key={i}
                          onClick={() =>
                            start(
                              `Teach me section: "${s.title}". Key points: ${s.key_points?.join(", ")}.`,
                              "teach",
                              activeCard?.topic,
                            )
                          }
                          className="text-xs px-2.5 py-1 bg-zinc-800 hover:bg-zinc-700
                                     rounded-lg text-zinc-300 transition-colors"
                        >
                          {i + 1}. {s.title}
                        </button>
                      ))}
                    </div>
                  </div>
                )}

                <StreamOutput text={text} streaming={streaming} />
              </>
            )}
          </div>

          {/* Input bar — always visible except profile */}
          {mode !== "profile" && mode !== "quiz" && (
            <div className="border-t border-zinc-800 p-3 flex-shrink-0">
              <div className="flex gap-2">
                <textarea
                  ref={inputRef}
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      send();
                    }
                  }}
                  placeholder={
                    mode === "teach"
                      ? "Ask a question about this topic…"
                      : mode === "work"
                      ? "Describe what you want to build or fix…"
                      : "Ask anything — news, explain, study, work…"
                  }
                  rows={2}
                  className="flex-1 bg-zinc-800 border border-zinc-700 rounded-xl
                             px-4 py-2.5 text-sm text-white placeholder-zinc-600
                             resize-none focus:outline-none focus:border-zinc-500
                             transition-colors"
                />
                <button
                  onClick={send}
                  disabled={!prompt.trim() || streaming}
                  className="px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500
                             disabled:opacity-30 disabled:cursor-not-allowed
                             text-white text-sm font-semibold transition-colors
                             flex-shrink-0"
                >
                  Send
                </button>
              </div>
              <p className="text-zinc-700 text-xs mt-1.5 ml-1">
                Enter to send · Shift+Enter for newline · Model: llama3.2 (local)
              </p>
            </div>
          )}
        </div>
      </div>
    </main>
  );
}
