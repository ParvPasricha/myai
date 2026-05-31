"use client";
import { useEffect, useState } from "react";

const WS_BASE =
  (typeof window !== "undefined" ? window.location.origin : "http://localhost:8000")
    .replace(/^http/, "ws")
    .replace(":3000", ":8000");

export interface GraphNode {
  id: string;
  type: "file" | "service" | "memory" | "decision";
  label: string;
  lang?: string;
  functions?: string[];
  imports?: string[];
  size?: number;
  alive?: boolean;
  domain?: string;
  port?: number;
  path?: string;
  mtime?: number;
}

export interface GraphEdge {
  from: string;
  to: string;
  type: "imports" | "calls" | "related";
}

export interface GraphState {
  nodes: GraphNode[];
  edges: GraphEdge[];
  last_updated: number;
  file_count?: number;
  service_count?: number;
}

const EMPTY: GraphState = { nodes: [], edges: [], last_updated: 0 };

export function useIntelligence() {
  const [graph, setGraph] = useState<GraphState>(EMPTY);
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket;
    let retry: ReturnType<typeof setTimeout>;

    const connect = () => {
      try {
        ws = new WebSocket(`${WS_BASE}/ws/intelligence`);
      } catch {
        retry = setTimeout(connect, 4000);
        return;
      }

      ws.onopen = () => setConnected(true);

      ws.onclose = () => {
        setConnected(false);
        retry = setTimeout(connect, 4000);
      };

      ws.onerror = () => ws.close();

      ws.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data as string);
          if (data.nodes !== undefined) {
            setGraph({
              nodes: data.nodes ?? [],
              edges: data.edges ?? [],
              last_updated: data.last_updated ?? 0,
              file_count: data.file_count,
              service_count: data.service_count,
            });
          }
        } catch {
          // ignore parse errors
        }
      };
    };

    connect();
    const heartbeat = setInterval(() => {
      if (ws?.readyState === WebSocket.OPEN) ws.send("ping");
    }, 25_000);

    return () => {
      clearTimeout(retry);
      clearInterval(heartbeat);
      ws?.close();
    };
  }, []);

  return { graph, connected };
}
