import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API, api, fmtBytes, type Stats } from "../api";
import { useLive } from "../components/live";
import { SeverityChip } from "../components/Status";

// the server relays the edge agent's preview, so this works locally and on a hosted single-port demo
const EDGE_PREVIEW = (import.meta.env.VITE_EDGE_PREVIEW as string | undefined) ?? `${API}/edge`;

interface LiveDemo {
  running: boolean;
  centre: string | null;
  started: string | null;
  centres: { id: string; label: string }[];
}

export function ControlRoom() {
  const { feed, connected, version } = useLive();
  const [stats, setStats] = useState<Stats | null>(null);
  const [previewOk, setPreviewOk] = useState(true);
  const [nonce, setNonce] = useState(0);
  const [edge, setEdge] = useState<{ offline: boolean; queue_depth: number; bytes_sent: number } | null>(null);
  const [demo, setDemo] = useState<LiveDemo | null>(null);
  const misses = useRef(0);
  const inFlight = useRef(false);
  const [starting, setStarting] = useState(false);
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const poll = () => {
      fetch(`${API}/api/v1/demo/live`).then((r) => (r.ok ? r.json() : null)).then(setDemo).catch(() => setDemo(null));
      // a busy edge device can miss a beat; only treat it as gone after a few missed polls
      if (inFlight.current) return;
      inFlight.current = true;
      fetch(`${EDGE_PREVIEW}/status`)
        .finally(() => (inFlight.current = false))
        .then((r) => (r.ok ? r.json() : Promise.reject()))
        .then((d) => {
          misses.current = 0;
          setEdge(d);
        })
        .catch(() => {
          if (++misses.current >= 3) setEdge(null);
        });
    };
    poll();
    const t = window.setInterval(() => {
      poll();
      setNow(Date.now());
    }, 1000);
    return () => window.clearInterval(t);
  }, []);
  // reconnect the preview by itself once an edge device starts streaming
  const streaming = edge !== null;
  useEffect(() => {
    if (streaming) {
      setPreviewOk(true);
      setNonce((n) => n + 1);
      setStarting(false);
    }
  }, [streaming]);
  const toggle = (on: boolean) => fetch(`${EDGE_PREVIEW}/offline?on=${on ? 1 : 0}`, { method: "POST" }).then((r) => (r.ok ? r.json() : {})).then((d) => setEdge((e) => (e ? { ...e, ...d } : e)));
  const start = (centre: string) => {
    setStarting(true);
    fetch(`${API}/api/v1/demo/live?centre=${centre}`, { method: "POST" })
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => (d ? setDemo(d) : setStarting(false)))
      .catch(() => setStarting(false));
  };
  const busy = starting || !!demo?.running;
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
          {previewOk && streaming ? (
            <img key={nonce} src={`${EDGE_PREVIEW}/stream.mjpg`} onError={() => setPreviewOk(false)} alt="Live, privacy-blurred edge preview"
              style={{ width: "100%", borderRadius: 8, background: "var(--surface-2)", minHeight: 240 }} />
          ) : (
            <div className="callout">
              {busy ? (
                <>
                  Starting the edge AI on recorded footage…
                  {demo?.started && <span className="muted"> {Math.max(0, Math.round((now - Date.parse(demo.started)) / 1000))} s</span>}
                  <div className="muted" style={{ marginTop: 6, fontSize: 12.5 }}>
                    About 20 seconds on a laptop; a free hosted server can take a minute or two.
                  </div>
                </>
              ) : demo && demo.centres.length > 0 ? (
                <>
                  No edge device is streaming. Run the real edge AI on a demo centre's recorded footage:
                  <div className="row" style={{ marginTop: 10, flexWrap: "wrap" }}>
                    {demo.centres.map((c) => (
                      <button key={c.id} className="btn primary" onClick={() => start(c.id)}>Start live run: {c.label}</button>
                    ))}
                  </div>
                </>
              ) : (
                <>
                  No edge device streaming a preview. Start one with:
                  <pre className="json" style={{ marginTop: 8 }}>.venv\Scripts\python scripts\demo.py live b --no-browser</pre>
                </>
              )}
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
                  <span className="secondary">{m.events} {m.events === 1 ? "event" : "events"}</span>
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
