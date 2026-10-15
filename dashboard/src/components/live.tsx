import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { WS_URL, type Alert } from "../api";

export interface LiveMsg {
  type: "alert" | "alert_update" | "ingest";
  alert?: Alert;
  centre_code?: string;
  events?: number;
  bytes?: number;
  at: number;
}

interface LiveState {
  connected: boolean;
  feed: LiveMsg[];        // newest first
  version: number;        // bumps on every message: pages refetch on change
}

const Ctx = createContext<LiveState>({ connected: false, feed: [], version: 0 });
export const useLive = () => useContext(Ctx);

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ connected: false, feed: [], version: 0 });
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let stopped = false;
    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        retry.current = 0;
        setState((s) => ({ ...s, connected: true }));
      };
      ws.onmessage = (e) => {
        const msg = { ...(JSON.parse(e.data) as Omit<LiveMsg, "at">), at: Date.now() };
        setState((s) => ({ ...s, feed: [msg, ...s.feed].slice(0, 200), version: s.version + 1 }));
      };
      ws.onclose = () => {
        setState((s) => ({ ...s, connected: false }));
        if (!stopped) timer = window.setTimeout(connect, Math.min(10000, 1000 * 2 ** retry.current++));
      };
    };
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}
