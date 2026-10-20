import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtBytes, type Stats } from "../api";
import { useLive } from "../components/live";
import { SeverityChip } from "../components/Status";

const EDGE_PREVIEW = (import.meta.env.VITE_EDGE_PREVIEW as string | undefined) ?? "http://127.0.0.1:8001";

export function ControlRoom() {
  const { feed, connected, version } = useLive();
  const [stats, setStats] = useState<Stats | null>(null);
  const [previewOk, setPreviewOk] = useState(true);
  const [nonce, setNonce] = useState(0);
  const [edge, setEdge] = useState<{ offline: boolean; queue_depth: number; bytes_sent: number } | null>(null);
  useEffect(() => {
    const t = window.setInterval(() => {
      fetch(`${EDGE_PREVIEW}/status`).then((r) => r.json()).then(setEdge).catch(() => setEdge(null));
    }, 1000);
    return () => window.clearInterval(t);
  }, []);
  const toggle = (on: boolean) => fetch(`${EDGE_PREVIEW}/offline?on=${on ? 1 : 0}`, { method: "POST" }).then((r) => r.json()).then((d) => setEdge((e) => (e ? { ...e, ...d } : e)));
  useEffect(() => {
    api.stats().then(setStats).catch(() => undefined);
  }, [version]);
  const ingest = feed.filter((m) => m.type === "ingest");
  const recentBytes = ingest.reduce((s, m) => s + (m.bytes ?? 0), 0);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Control room</h1>
          <p>Live view of an edge device processing a camera, and events as they reach the server.</p>
        </div>
        <div className="row">
          {connected ? <span className="row" style={{ gap: 6 }}><span className="pulse" /> Live</span> : <span className="muted">Reconnecting…</span>}
        </div>
      </div>
      <div className="grid two">
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Edge device view</h2>
              <p>What the on-site AI sees: people pixelated, training area outlined, count overlaid. This image stays on site.</p>
            </div>
            <button className="btn" onClick={() => { setPreviewOk(true); setNonce((n) => n + 1); }}>Reconnect</button>
          </div>
          {edge && (
            <div className="row" style={{ marginBottom: 10 }}>
              {edge.offline ? (
                <span className="chip"><span className="dot" style={{ background: "var(--critical)" }} />Uplink down: queuing on device</span>
              ) : (
                <span className="chip"><span className="dot" style={{ background: "var(--good)" }} />Uplink up</span>
              )}
              <span className="secondary">Queue <b>{edge.queue_depth}</b> events · sent <b>{fmtBytes(edge.bytes_sent)}</b></span>
              <span className="spacer" />
              {edge.offline ? (
                <button className="btn primary" onClick={() => void toggle(false)}>Restore network</button>
              ) : (
                <button className="btn" onClick={() => void toggle(true)}>Cut network</button>
              )}
            </div>
          )}
          {previewOk ? (
            <img key={nonce} src={`${EDGE_PREVIEW}/stream.mjpg`} onError={() => setPreviewOk(false)} alt="Live, privacy-blurred edge preview"
              style={{ width: "100%", borderRadius: 8, background: "var(--surface-2)", minHeight: 240 }} />
          ) : (
            <div className="callout">
              No edge device streaming a preview. Start one with:
              <pre className="json" style={{ marginTop: 8 }}>.venv\Scripts\python -m edge.agent --config configs/centres/demo_b.yaml --realtime --preview</pre>
            </div>
          )}
        </div>
        <div className="card" style={{ display: "flex", flexDirection: "column" }}>
          <div className="card-head">
            <div>
              <h2>Incoming</h2>
              <p>{ingest.length} uploads this session · {fmtBytes(recentBytes)} received</p>
            </div>
            <span className="muted" style={{ fontSize: 12 }}>Total {stats ? fmtBytes(stats.bytes_sent) : "—"}</span>
          </div>
          <div style={{ overflow: "auto", maxHeight: 520, display: "flex", flexDirection: "column", gap: 8 }}>
            {feed.length === 0 && <div className="empty">Waiting for edge devices…</div>}
            {feed.map((m, i) =>
              m.type === "ingest" ? (
                <div key={i} className="row" style={{ fontSize: 12.5 }}>
                  <span className="muted mono">{new Date(m.at).toLocaleTimeString("en-IN", { hour12: false })}</span>
                  <Link to={`/centres/${m.centre_code}`}>{m.centre_code}</Link>
                  <span className="secondary">{m.events} events</span>
                  <span className="spacer" />
                  <span className="mono muted">{fmtBytes(m.bytes ?? 0)}</span>
                </div>
              ) : m.alert ? (
                <div key={i} className="card" style={{ padding: 10 }}>
                  <div className="row">
                    <SeverityChip s={m.alert.severity} />
                    <span className="muted mono" style={{ fontSize: 12 }}>{new Date(m.at).toLocaleTimeString("en-IN", { hour12: false })}</span>
                    <span className="tag">{m.type === "alert" ? "new" : "updated"}</span>
                  </div>
                  <div style={{ marginTop: 4 }}>{m.alert.title}</div>
                  <Link to={`/centres/${m.alert.centre_code}`} style={{ fontSize: 12.5 }}>{m.alert.centre_name}</Link>
                </div>
              ) : null,
            )}
          </div>
        </div>
      </div>
    </>
  );
}
