"use client";
import { useEffect, useState, useCallback } from "react";

const API = "http://localhost:8000";
const INTERVAL = 15_000;

export interface BrainState { focus: number; energy: number; stress: number }
export interface LLMStats { requests_24h: number; errors_1h: number; latency_p95: number }
export interface InfraStats { redis: boolean; ollama: boolean; mqtt: boolean; deadman_s: number }
export interface HttpEndpoint { method: string; path: string; status: string; count: number }
export interface AlertStat { name: string; total: number }

export interface DashboardMetrics {
  ts: number;
  brain_state: BrainState;
  llm: LLMStats;
  infra: InfraStats;
  http_endpoints: HttpEndpoint[];
  alerts: AlertStat[];
}

export interface HistoryPoint { ts: number; value: number }

const EMPTY: DashboardMetrics = {
  ts: 0,
  brain_state: { focus: 0, energy: 0, stress: 0 },
  llm: { requests_24h: 0, errors_1h: 0, latency_p95: 0 },
  infra: { redis: false, ollama: false, mqtt: false, deadman_s: 0 },
  http_endpoints: [],
  alerts: [],
};

export function useMetrics() {
  const [data, setData] = useState<DashboardMetrics>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(0);

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${API}/metrics/dashboard`);
      if (r.ok) {
        setData(await r.json());
        setLastRefresh(Date.now());
      }
    } catch { /* silent — keep showing last data */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => {
    fetch_();
    const id = setInterval(fetch_, INTERVAL);
    return () => clearInterval(id);
  }, [fetch_]);

  return { data, loading, lastRefresh, refresh: fetch_ };
}

export async function fetchHistory(
  metric: string,
  minutes = 180,
): Promise<HistoryPoint[]> {
  try {
    const r = await fetch(`${API}/metrics/history?metric=${metric}&minutes=${minutes}`);
    if (!r.ok) return [];
    const j = await r.json();
    return j.points ?? [];
  } catch {
    return [];
  }
}
