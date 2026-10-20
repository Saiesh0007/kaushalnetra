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
  version: number;        // bumps on new messages (at most every REFETCH_MS): pages refetch on change
}

const Ctx = createContext<LiveState>({ connected: false, feed: [], version: 0 });
export const useLive = () => useContext(Ctx);

// A live run sends dozens of messages; refetching on each one queues slow requests faster than the server answers.
const REFETCH_MS = 5000;

export function LiveProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<LiveState>({ connected: false, feed: [], version: 0 });
  const retry = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let bumpTimer: number | undefined;
    let lastBump = 0;
    let stopped = false;
    const bump = () => {
      bumpTimer = undefined;
      lastBump = Date.now();
      setState((s) => ({ ...s, version: s.version + 1 }));
    };
    const connect = () => {
      ws = new WebSocket(WS_URL);
      ws.onopen = () => {
        retry.current = 0;
        setState((s) => ({ ...s, connected: true }));
      };
      ws.onmessage = (e) => {
        const msg = { ...(JSON.parse(e.data) as Omit<LiveMsg, "at">), at: Date.now() };
        setState((s) => ({ ...s, feed: [msg, ...s.feed].slice(0, 200) }));
        if (bumpTimer === undefined) bumpTimer = window.setTimeout(bump, Math.max(0, lastBump + REFETCH_MS - Date.now()));
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
      window.clearTimeout(bumpTimer);
      ws?.close();
    };
  }, []);

  return <Ctx.Provider value={state}>{children}</Ctx.Provider>;
}
