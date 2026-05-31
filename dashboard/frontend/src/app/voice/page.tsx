"use client";

import { useState, useEffect, useRef, useCallback } from "react";

const API = "http://localhost:8000";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Effects {
  robotic: number;
  warmth: number;
  emotion_intensity: number;
  pitch_shift: number;
  tempo: number;
  mood: string;
}

interface VoiceConfig {
  engine: string;
  reference_clip_loaded: boolean;
  chatterbox: { exaggeration: number; cfg_weight: number };
  edge: { voice: string; rate: string; pitch: string };
  effects: Effects;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

function getToken() {
  if (typeof window === "undefined") return "";
  return localStorage.getItem("jarvis_token") ?? "";
}

async function apiFetch(path: string, opts: RequestInit = {}) {
  const token = getToken();
  const res = await fetch(`${API}${path}`, {
    ...opts,
    headers: {
      "Content-Type": "application/json",
      Authorization: token ? `Bearer ${token}` : "",
      ...(opts.headers ?? {}),
    },
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res;
}

// ── Sub-components ────────────────────────────────────────────────────────────

function SliderRow({
  label,
  value,
  min,
  max,
  step = 1,
  unit = "",
  leftLabel,
  rightLabel,
  onChange,
  color = "cyan",
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  leftLabel?: string;
  rightLabel?: string;
  onChange: (v: number) => void;
  color?: string;
}) {
  const pct = ((value - min) / (max - min)) * 100;
  const colors: Record<string, string> = {
    cyan:   "accent-cyan-400",
    blue:   "accent-blue-400",
    purple: "accent-purple-400",
    amber:  "accent-amber-400",
    green:  "accent-green-400",
  };
  return (
    <div className="space-y-1.5">
      <div className="flex justify-between items-center">
        <span className="text-sm font-medium text-zinc-300">{label}</span>
        <span className="text-sm font-mono text-zinc-400 min-w-[3.5rem] text-right">
          {typeof value === "number" && !Number.isInteger(value)
            ? value.toFixed(2)
            : value}
          {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className={`w-full h-2 rounded-full bg-zinc-700 outline-none cursor-pointer ${colors[color] ?? colors.cyan}`}
      />
      {(leftLabel || rightLabel) && (
        <div className="flex justify-between text-xs text-zinc-600">
          <span>{leftLabel}</span>
          <span>{rightLabel}</span>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  icon,
  children,
}: {
  title: string;
  icon: string;
  children: React.ReactNode;
}) {
  return (
    <div className="bg-zinc-900 border border-zinc-800 rounded-2xl p-5 space-y-4">
      <h2 className="text-xs font-semibold tracking-widest uppercase text-zinc-500 flex items-center gap-2">
        <span>{icon}</span>
        {title}
      </h2>
      {children}
    </div>
  );
}

// ── Waveform visualizer ───────────────────────────────────────────────────────

function WaveformBar({ active }: { active: boolean }) {
  const bars = Array.from({ length: 20 }, (_, i) => i);
  return (
    <div className="flex items-end gap-0.5 h-8">
      {bars.map((i) => (
        <div
          key={i}
          className={`w-1 rounded-full transition-all duration-75 ${
            active ? "bg-cyan-400" : "bg-zinc-700"
          }`}
          style={{
            height: active
              ? `${20 + Math.sin(Date.now() / 200 + i * 0.6) * 14}px`
              : "4px",
            animationDelay: `${i * 30}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

const MOODS = ["calm", "serious", "urgent", "cheerful"];

const DEFAULT_CONFIG: VoiceConfig = {
  engine: "chatterbox",
  reference_clip_loaded: false,
  chatterbox: { exaggeration: 0.5, cfg_weight: 0.5 },
  edge: { voice: "en-GB-RyanNeural", rate: "-5%", pitch: "-10Hz" },
  effects: {
    robotic: 0,
    warmth: 25,
    emotion_intensity: 50,
    pitch_shift: 0,
    tempo: 1.0,
    mood: "serious",
  },
};

export default function VoiceEditorPage() {
  const [cfg, setCfg]               = useState<VoiceConfig>(DEFAULT_CONFIG);
  const [previewText, setPreviewText] = useState(
    "Initializing Jarvis. All systems online. How may I assist you today, sir?"
  );
  const [previewing, setPreviewing] = useState(false);
  const [saving, setSaving]         = useState(false);
  const [saved, setSaved]           = useState(false);
  const [uploading, setUploading]   = useState(false);
  const [status, setStatus]         = useState("");
  const [token, setToken]           = useState("");
  const audioRef  = useRef<HTMLAudioElement | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const waveTimer = useRef<ReturnType<typeof setInterval> | null>(null);
  const [waveActive, setWaveActive] = useState(false);

  // Prompt for token once
  useEffect(() => {
    const t = localStorage.getItem("jarvis_token") ?? "";
    if (!t) {
      const input = prompt("Jarvis API token:");
      if (input) localStorage.setItem("jarvis_token", input);
    }
    setToken(localStorage.getItem("jarvis_token") ?? "");
    loadConfig();
  }, []);

  async function loadConfig() {
    try {
      const res = await apiFetch("/voice-editor/config");
      const data = await res.json();
      setCfg(data);
    } catch (e) {
      setStatus("Could not load config — is the server running?");
    }
  }

  function updateEffect<K extends keyof Effects>(key: K, val: Effects[K]) {
    setCfg((c) => ({ ...c, effects: { ...c.effects, [key]: val } }));
    setSaved(false);
  }

  function updateChatterbox(key: string, val: number) {
    setCfg((c) => ({ ...c, chatterbox: { ...c.chatterbox, [key]: val } }));
    setSaved(false);
  }

  async function saveConfig() {
    setSaving(true);
    try {
      await apiFetch("/voice-editor/config", {
        method: "PUT",
        body: JSON.stringify({
          engine: cfg.engine,
          chatterbox: cfg.chatterbox,
          effects: cfg.effects,
        }),
      });
      setSaved(true);
      setStatus("Saved.");
      setTimeout(() => setStatus(""), 2000);
    } catch (e: any) {
      setStatus("Save failed: " + e.message);
    } finally {
      setSaving(false);
    }
  }

  async function playPreview() {
    if (previewing) return;
    setPreviewing(true);
    setWaveActive(true);
    setStatus("Generating preview...");
    try {
      const res = await apiFetch("/voice-editor/preview", {
        method: "POST",
        body: JSON.stringify({
          text: previewText,
          effects_override: cfg.effects,
        }),
      });
      const blob = await res.blob();
      const url  = URL.createObjectURL(blob);
      if (audioRef.current) {
        audioRef.current.src = url;
        audioRef.current.play();
        audioRef.current.onended = () => {
          setWaveActive(false);
          setStatus("");
        };
      }
      setStatus("");
    } catch (e: any) {
      setStatus("Preview failed: " + e.message);
      setWaveActive(false);
    } finally {
      setPreviewing(false);
    }
  }

  async function uploadReference(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    setStatus(`Uploading ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const t = localStorage.getItem("jarvis_token") ?? "";
      const res = await fetch(`${API}/voice-editor/upload-reference`, {
        method: "POST",
        headers: { Authorization: t ? `Bearer ${t}` : "" },
        body: form,
      });
      if (!res.ok) throw new Error(await res.text());
      const data = await res.json();
      setCfg((c) => ({ ...c, reference_clip_loaded: true }));
      setStatus(`Reference loaded (${data.size_mb} MB). Preview to hear it.`);
    } catch (e: any) {
      setStatus("Upload failed: " + e.message);
    } finally {
      setUploading(false);
    }
  }

  async function applyMoodPreset(mood: string) {
    updateEffect("mood", mood);
    try {
      const res = await apiFetch("/voice-editor/presets");
      const presets = await res.json();
      if (presets[mood]) {
        const p = presets[mood];
        setCfg((c) => ({
          ...c,
          effects: {
            ...c.effects,
            mood,
            pitch_shift:      p.pitch_shift      ?? c.effects.pitch_shift,
            tempo:             p.tempo             ?? c.effects.tempo,
            emotion_intensity: p.emotion_intensity ?? c.effects.emotion_intensity,
          },
        }));
      }
    } catch {}
    setSaved(false);
  }

  async function resetConfig() {
    if (!confirm("Reset all voice settings to defaults?")) return;
    await apiFetch("/voice-editor/reset", { method: "POST" });
    await loadConfig();
    setStatus("Reset to defaults.");
    setTimeout(() => setStatus(""), 2000);
  }

  const fx = cfg.effects;

  return (
    <main className="min-h-screen bg-zinc-950 text-white p-4 md:p-8">
      <audio ref={audioRef} />

      {/* Header */}
      <div className="max-w-3xl mx-auto mb-8 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
            <span className="text-cyan-400">◈</span> Voice Editor
          </h1>
          <p className="text-zinc-500 text-sm mt-1">
            Tune Jarvis's voice texture in real-time
          </p>
        </div>
        <div className="flex items-center gap-2">
          {cfg.reference_clip_loaded ? (
            <span className="text-xs text-cyan-400 bg-cyan-400/10 border border-cyan-400/20 px-2 py-1 rounded-full">
              Reference loaded
            </span>
          ) : (
            <span className="text-xs text-amber-400 bg-amber-400/10 border border-amber-400/20 px-2 py-1 rounded-full">
              No reference clip
            </span>
          )}
        </div>
      </div>

      <div className="max-w-3xl mx-auto space-y-4">

        {/* Reference clip upload */}
        <Section icon="🎤" title="Voice Reference">
          <p className="text-sm text-zinc-400">
            Upload a WAV or MP3 clip (ideally 10–30 seconds) of the target voice. Jarvis will
            clone this texture for all speech.
          </p>
          <div className="flex items-center gap-3">
            <button
              onClick={() => fileInput.current?.click()}
              disabled={uploading}
              className="px-4 py-2 bg-zinc-800 hover:bg-zinc-700 disabled:opacity-50 rounded-xl text-sm font-medium transition-colors border border-zinc-700"
            >
              {uploading ? "Uploading…" : "Upload clip"}
            </button>
            <input
              ref={fileInput}
              type="file"
              accept=".wav,.mp3,.m4a"
              className="hidden"
              onChange={uploadReference}
            />
            <span className="text-sm text-zinc-500">
              {cfg.reference_clip_loaded
                ? "reference.wav is active"
                : "No clip yet — using en-GB-RyanNeural"}
            </span>
          </div>
        </Section>

        {/* Mood presets */}
        <Section icon="🎭" title="Mood Preset">
          <div className="grid grid-cols-4 gap-2">
            {MOODS.map((m) => (
              <button
                key={m}
                onClick={() => applyMoodPreset(m)}
                className={`py-2 rounded-xl text-sm font-medium capitalize transition-all border ${
                  fx.mood === m
                    ? "bg-cyan-400/20 border-cyan-400/50 text-cyan-300"
                    : "bg-zinc-800 border-zinc-700 hover:bg-zinc-700 text-zinc-300"
                }`}
              >
                {m}
              </button>
            ))}
          </div>
        </Section>

        {/* Main sliders */}
        <Section icon="🤖" title="Character">
          <SliderRow
            label="Robotic Filter"
            value={fx.robotic}
            min={0} max={100}
            leftLabel="Natural"
            rightLabel="Full robot"
            color="cyan"
            onChange={(v) => updateEffect("robotic", v)}
          />
          <SliderRow
            label="Warmth"
            value={fx.warmth}
            min={0} max={100}
            leftLabel="Dry / Cold"
            rightLabel="Warm / Resonant"
            color="amber"
            onChange={(v) => updateEffect("warmth", v)}
          />
          <SliderRow
            label="Emotion Intensity"
            value={fx.emotion_intensity}
            min={0} max={100}
            leftLabel="Flat / Compressed"
            rightLabel="Wide / Expressive"
            color="purple"
            onChange={(v) => updateEffect("emotion_intensity", v)}
          />
        </Section>

        <Section icon="🎼" title="Pitch & Tempo">
          <SliderRow
            label="Pitch Shift"
            value={fx.pitch_shift}
            min={-6} max={6}
            step={0.5}
            unit=" st"
            leftLabel="-6 semitones"
            rightLabel="+6 semitones"
            color="blue"
            onChange={(v) => updateEffect("pitch_shift", v)}
          />
          <SliderRow
            label="Tempo"
            value={fx.tempo}
            min={0.75} max={1.5}
            step={0.01}
            leftLabel="0.75× slower"
            rightLabel="1.5× faster"
            color="green"
            onChange={(v) => updateEffect("tempo", v)}
          />
        </Section>

        {/* Chatterbox model controls */}
        <Section icon="⚙️" title="Voice Cloning (Chatterbox)">
          <SliderRow
            label="Exaggeration"
            value={cfg.chatterbox.exaggeration}
            min={0.25} max={0.75}
            step={0.01}
            leftLabel="Subdued"
            rightLabel="Expressive"
            color="purple"
            onChange={(v) => updateChatterbox("exaggeration", v)}
          />
          <SliderRow
            label="Reference Adherence"
            value={cfg.chatterbox.cfg_weight}
            min={0} max={1}
            step={0.01}
            leftLabel="Ignore reference"
            rightLabel="Strict reference"
            color="cyan"
            onChange={(v) => updateChatterbox("cfg_weight", v)}
          />
          <div className="text-xs text-zinc-600 mt-1">
            Engine:{" "}
            <span className="text-zinc-400 font-mono">
              {cfg.reference_clip_loaded ? "Chatterbox + reference clip" : "Edge-TTS (no clip uploaded)"}
            </span>
          </div>
        </Section>

        {/* Preview */}
        <Section icon="▶" title="Preview">
          <textarea
            value={previewText}
            onChange={(e) => setPreviewText(e.target.value)}
            rows={2}
            className="w-full bg-zinc-800 border border-zinc-700 rounded-xl px-3 py-2 text-sm text-zinc-200 resize-none outline-none focus:border-cyan-600"
          />
          <div className="flex items-center gap-4">
            <button
              onClick={playPreview}
              disabled={previewing}
              className="px-5 py-2.5 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 disabled:cursor-not-allowed text-black font-semibold rounded-xl text-sm transition-colors"
            >
              {previewing ? "Generating…" : "▶ Preview"}
            </button>
            <WaveformBar active={waveActive} />
            {status && (
              <span className="text-xs text-zinc-400 ml-auto">{status}</span>
            )}
          </div>
        </Section>

        {/* Save / Reset */}
        <div className="flex gap-3 pb-8">
          <button
            onClick={saveConfig}
            disabled={saving || saved}
            className="flex-1 py-3 bg-cyan-500 hover:bg-cyan-400 disabled:opacity-60 text-black font-bold rounded-2xl text-sm transition-colors"
          >
            {saving ? "Saving…" : saved ? "✓ Saved" : "Save Settings"}
          </button>
          <button
            onClick={resetConfig}
            className="px-5 py-3 bg-zinc-800 hover:bg-zinc-700 text-zinc-400 rounded-2xl text-sm transition-colors border border-zinc-700"
          >
            Reset
          </button>
        </div>

      </div>
    </main>
  );
}
