// dev: separate API server; production build: dashboard is served by the API itself (same origin)
export const API: string = (import.meta.env.VITE_API as string | undefined) ?? (import.meta.env.PROD ? "" : "http://127.0.0.1:8000");
export const WS_URL = (API || window.location.origin).replace(/^http/, "ws") + "/ws";

export type Band = "low" | "medium" | "high";
export type Severity = "critical" | "warning" | "info";

export interface Risk {
  score: number;
  band: Band;
  components: Record<string, number>;
  weights: Record<string, number>;
}
export interface Device {
  last_heartbeat: string | null;
  bytes_sent: number;
  raw_video_bytes: number;
  queue_depth: number;
  uptime_pct: number;
  mode: string;
}
export interface Centre {
  id: number;
  code: string;
  name: string;
  state: string;
  district: string;
  lat: number;
  lon: number;
  scheme: string;
  trade: string;
  sanctioned_seats: number;
  simulated: boolean;
  risk: Risk;
  open_alerts: number;
  device: Device | null;
  cameras?: { id: string; name: string; coverage: number; mode: string; last_seen: string | null }[];
}
export interface SessionRow {
  session_ref: string;
  batch: string;
  start: string;
  end: string;
  claimed: number | null;
  observed: number | null;
  band: number | null;
  gap: number | null;
  gap_pct: number | null;
  flagged: boolean;
  n_windows: number;
  thumb_ids?: string[];
}
export interface Item {
  item_key: string;
  class_name: string;
  description: string;
  cam_key: string | null;
  camera_verifiable: boolean;
  state: string;
  sim: number | null;
  last_checked: string | null;
  thumb_id: string | null;
  history: { ts: string; state: string; sim: number | null }[];
  usage: { session_ref: string; interaction_min: number }[];
}
export interface Alert {
  id: number;
  key: string;
  centre_id: number;
  centre_code: string | null;
  centre_name: string | null;
  kind: string;
  severity: Severity;
  status: string;
  title: string;
  detail: string;
  evidence: Record<string, unknown> & { thumb_ids?: string[] };
  opened_at: string;
  updated_at: string;
  assignee: string | null;
  resolution_note: string | null;
}
export interface Stats {
  centres: number;
  real_centres: number;
  bands: Record<Band, number>;
  open_alerts: Partial<Record<Severity, number>>;
  bytes_sent: number;
  raw_video_bytes: number;
  pipeline_bytes_sent: number;
  pipeline_raw_video_bytes: number;
  cameras: number;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(API + path, { headers: { "content-type": "application/json" }, ...init });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json() as Promise<T>;
}

export const api = {
  stats: () => req<Stats>("/api/v1/stats"),
  centres: () => req<Centre[]>("/api/v1/centres"),
  centre: (code: string) => req<Centre>(`/api/v1/centres/${encodeURIComponent(code)}`),
  attendance: (code: string) => req<SessionRow[]>(`/api/v1/centres/${encodeURIComponent(code)}/attendance`),
  inventory: (code: string) => req<Item[]>(`/api/v1/centres/${encodeURIComponent(code)}/inventory`),
  alerts: (q: Record<string, string> = {}) => req<Alert[]>("/api/v1/alerts?" + new URLSearchParams(q).toString()),
  patchAlert: (id: number, body: Partial<Pick<Alert, "status" | "assignee" | "resolution_note">>) =>
    req<Alert>(`/api/v1/alerts/${id}`, { method: "PATCH", body: JSON.stringify({ ...body, actor: "demo-monitor" }) }),
};

export const thumbUrl = (id: string) => `${API}/api/v1/thumbnails/${id}`;

/* formatting */
const IST: Intl.DateTimeFormatOptions = { timeZone: "Asia/Kolkata" };
export const fmtDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-IN", { ...IST, day: "2-digit", month: "short" }) : "—";
export const fmtDateTime = (iso: string | null) =>
  iso
    ? new Date(iso).toLocaleString("en-IN", { ...IST, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false })
    : "—";
export const fmtBytes = (n: number) => {
  if (n < 1024) return `${n} B`;
  const u = ["KB", "MB", "GB", "TB"];
  let v = n / 1024;
  let i = 0;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v >= 100 ? v.toFixed(0) : v.toFixed(1)} ${u[i]}`;
};
export const fmtInt = (n: number) => n.toLocaleString("en-IN");
export const ago = (iso: string | null) => {
  if (!iso) return "never";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return `${Math.round(s / 86400)} d ago`;
};
