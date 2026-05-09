"use client";
import { useEffect, useRef, useState } from "react";

export interface DashboardState {
  current_activity: string;
  focus_score: number;
  energy_score: number;
  stress_score: number;
  deep_work: boolean;
  location: string;
  emotion: string | null;
  today_topic: string | null;
  quiz_status: string;
  mic_stage: string;
  last_updated: string;
}

const DEFAULT: DashboardState = {
  current_activity: "—",
  focus_score: 5,
  energy_score: 5,
  stress_score: 3,
  deep_work: false,
  location: "unknown",
  emotion: null,
  today_topic: null,
  quiz_status: "pending",
  mic_stage: "push_to_talk",
  last_updated: new Date().toISOString(),
};

const API = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const WS  = API.replace(/^http/, "ws");

export function useDashboard(token?: string) {
  const [state, setState] = useState<DashboardState>(DEFAULT);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Fetch initial state via REST
    const url = token
      ? `${API}/dashboard/public?token=${token}`
      : `${API}/dashboard/public`;

    fetch(url)
      .then((r) => r.json())
      .then((d) => setState((prev) => ({ ...prev, ...d })))
      .catch(() => {});

    // WebSocket for live updates
    const wsUrl = token
      ? `${WS}/ws/dashboard?token=${token}`
      : `${WS}/ws/dashboard`;

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => setConnected(true);
      ws.onclose = () => {
        setConnected(false);
        setTimeout(connect, 3000); // reconnect after 3s
      };
      ws.onerror = () => ws.close();
      ws.onmessage = (evt) => {
        try {
          const data = JSON.parse(evt.data);
          if (data.type !== "pong") setState((prev) => ({ ...prev, ...data }));
        } catch {}
      };

      // Keepalive ping every 25s
      const ping = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) ws.send("ping");
      }, 25000);

      ws.onclose = () => {
        clearInterval(ping);
        setConnected(false);
        setTimeout(connect, 3000);
      };
    };

    connect();
    return () => wsRef.current?.close();
  }, [token]);

  return { state, connected };
}
