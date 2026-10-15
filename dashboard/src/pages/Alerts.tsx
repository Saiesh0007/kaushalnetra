import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, fmtDateTime, type Alert } from "../api";
import { useLive } from "../components/live";
import { SeverityChip, StatusChip } from "../components/Status";
import { Lightbox, Thumb } from "../components/Thumb";

const KIND: Record<string, string> = {
  attendance: "Attendance",
  over_occupancy: "Over-occupancy",
  item_missing: "Equipment missing",
  item_changed: "Equipment changed",
  item_unused: "Equipment unused",
  tamper: "Camera tamper",
};

export function AlertDrawer({ alert, onClose, onChange }: { alert: Alert; onClose: () => void; onChange: (a: Alert) => void }) {
  const [note, setNote] = useState("");
  const [assignee, setAssignee] = useState(alert.assignee ?? "");
  const [err, setErr] = useState("");
  const [big, setBig] = useState<string | null>(null);
  const act = async (body: Parameters<typeof api.patchAlert>[1]) => {
    setErr("");
    try {
      onChange(await api.patchAlert(alert.id, body));
    } catch (e) {
      setErr(String(e));
    }
  };
  const ev = alert.evidence ?? {};
  const thumbs = (ev.thumb_ids ?? []) as string[];
  const { thumb_ids: _t, thresholds, checks, ...rest } = ev as Record<string, unknown>;
  void _t;
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" aria-label="Alert detail">
        <div className="row">
          <SeverityChip s={alert.severity} />
          <StatusChip status={alert.status} />
          <span className="tag">{KIND[alert.kind] ?? alert.kind}</span>
          <span className="spacer" />
          <button className="btn" onClick={onClose}>Close</button>
        </div>
        <div>
          <h2>{alert.title}</h2>
          <p className="secondary" style={{ margin: "6px 0 0" }}>{alert.detail}</p>
          <p className="muted" style={{ margin: "6px 0 0", fontSize: 12.5 }}>
            <Link to={`/centres/${alert.centre_code}`}>{alert.centre_name}</Link> · opened {fmtDateTime(alert.opened_at)} · updated {fmtDateTime(alert.updated_at)}
          </p>
        </div>
        {thumbs.length > 0 && (
          <div>
            <h3 style={{ marginBottom: 8 }}>Evidence</h3>
            <div className="thumbs">{thumbs.map((t) => <Thumb key={t} id={t} w={160} onOpen={setBig} />)}</div>
            <p className="muted" style={{ fontSize: 12, margin: "6px 0 0" }}>People are pixelated on the edge device. Viewing evidence is logged.</p>
          </div>
        )}
        {Array.isArray(checks) && (
          <div>
            <h3 style={{ marginBottom: 6 }}>Check history</h3>
            <table>
              <thead><tr><th>Time</th><th>State</th><th className="num">Similarity</th></tr></thead>
              <tbody>
                {(checks as { ts: string; state: string; sim: number | null }[]).map((c) => (
                  <tr key={c.ts}><td>{fmtDateTime(c.ts + "Z")}</td><td>{c.state.replace("candidate_", "")}</td><td className="num">{c.sim ?? "—"}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <details>
          <summary className="muted">Evidence data and thresholds used</summary>
          <pre className="json">{JSON.stringify({ ...rest, thresholds }, null, 2)}</pre>
        </details>
        <div className="card" style={{ padding: 12 }}>
          <h3 style={{ marginBottom: 8 }}>Action</h3>
          <div className="row">
            <button className="btn" disabled={alert.status !== "open"} onClick={() => act({ status: "ack" })}>Acknowledge</button>
            <input placeholder="Inspector name" value={assignee} onChange={(e) => setAssignee(e.target.value)} style={{ flex: 1, minWidth: 140 }} />
            <button className="btn" disabled={!assignee.trim()} onClick={() => act({ status: "assigned", assignee })}>Assign</button>
          </div>
          <textarea rows={2} placeholder="Resolution note (required to resolve or dismiss)" value={note} onChange={(e) => setNote(e.target.value)} style={{ marginTop: 8 }} />
          <div className="row" style={{ marginTop: 8 }}>
            <button className="btn primary" disabled={!note.trim()} onClick={() => act({ status: "resolved", resolution_note: note })}>Resolve</button>
            <button className="btn" disabled={!note.trim()} onClick={() => act({ status: "dismissed", resolution_note: note })}>Dismiss as false alarm</button>
          </div>
          {alert.resolution_note && <p className="muted" style={{ fontSize: 12.5 }}>Note: {alert.resolution_note}</p>}
          {err && <p style={{ color: "var(--critical-text)" }}>{err}</p>}
        </div>
      </aside>
      <Lightbox id={big} onClose={() => setBig(null)} />
    </>
  );
}

export function Alerts() {
  const { version } = useLive();
  const [rows, setRows] = useState<Alert[]>([]);
  const [status, setStatus] = useState("open,ack,assigned");
  const [severity, setSeverity] = useState("critical,warning");
  const [kind, setKind] = useState("");
  const [real, setReal] = useState(false);
  const [sel, setSel] = useState<Alert | null>(null);

  useEffect(() => {
    const q: Record<string, string> = {};
    if (status) q.status = status;
    if (severity) q.severity = severity;
    if (kind) q.kind = kind;
    api.alerts(q).then(setRows).catch(() => undefined);
  }, [status, severity, kind, version]);

  const shown = real ? rows.filter((a) => !a.centre_code?.startsWith("KN-SIM")) : rows;
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Alerts</h1>
          <p>{shown.length} alerts · every alert carries the evidence and thresholds that produced it</p>
        </div>
        <div className="row">
          <select value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
            <option value="open,ack,assigned">Active</option>
            <option value="open">Open</option>
            <option value="resolved,dismissed">Closed</option>
            <option value="">Any status</option>
          </select>
          <select value={severity} onChange={(e) => setSeverity(e.target.value)} aria-label="Severity">
            <option value="critical,warning">Critical + warning</option>
            <option value="critical">Critical</option>
            <option value="">Any severity</option>
          </select>
          <select value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Type">
            <option value="">All types</option>
            {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
          </select>
          <label className="row" style={{ gap: 6 }}><input type="checkbox" checked={real} onChange={(e) => setReal(e.target.checked)} /> AI-pipeline centres only</label>
        </div>
      </div>
      <div className="card" style={{ overflow: "auto" }}>
        <table>
          <thead>
            <tr><th>Severity</th><th>Alert</th><th>Centre</th><th>Type</th><th>Status</th><th>Opened</th></tr>
          </thead>
          <tbody>
            {shown.map((a) => (
              <tr key={a.id} className="click" onClick={() => setSel(a)}>
                <td><SeverityChip s={a.severity} /></td>
                <td style={{ maxWidth: 420 }}>{a.title}</td>
                <td>{a.centre_name}</td>
                <td className="muted">{KIND[a.kind] ?? a.kind}</td>
                <td><StatusChip status={a.status} /></td>
                <td className="muted">{fmtDateTime(a.opened_at)}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={6} className="empty">No alerts match these filters.</td></tr>}
          </tbody>
        </table>
      </div>
      {sel && (
        <AlertDrawer
          alert={sel}
          onClose={() => setSel(null)}
          onChange={(a) => {
            setSel(a);
            setRows((r) => r.map((x) => (x.id === a.id ? a : x)));
          }}
        />
      )}
    </>
  );
}
