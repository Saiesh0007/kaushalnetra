import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { API, ago, api, fmtBytes, fmtDate, fmtDateTime, fmtInt, type Alert, type Centre as C, type Item, type SessionRow } from "../api";
import { AttendanceChart, RiskBreakdown } from "../components/AttendanceChart";
import { useLive } from "../components/live";
import { BandChip, Chip, ItemChip, SeverityChip, StatusChip, itemTone, toneColor } from "../components/Status";
import { Lightbox, Thumb } from "../components/Thumb";
import { AlertDrawer } from "./Alerts";

type Tab = "attendance" | "equipment" | "alerts" | "privacy";

export function Centre() {
  const { code = "" } = useParams();
  const { version } = useLive();
  const [c, setC] = useState<C | null>(null);
  const [sessions, setSessions] = useState<SessionRow[]>([]);
  const [items, setItems] = useState<Item[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [params] = useSearchParams();
  const [tab, setTab] = useState<Tab>((params.get("tab") as Tab) || "attendance");
  const [pick, setPick] = useState<SessionRow | null>(null);
  const [sel, setSel] = useState<Alert | null>(null);
  const [big, setBig] = useState<string | null>(null);
  const [err, setErr] = useState("");

  useEffect(() => {
    api.centre(code).then(setC).catch((e) => setErr(String(e)));
    api.attendance(code).then(setSessions).catch(() => undefined);
    api.inventory(code).then(setItems).catch(() => undefined);
    api.alerts({ centre: code }).then(setAlerts).catch(() => undefined);
  }, [code, version]);

  const flagged = sessions.filter((s) => s.flagged).length;
  const observed = sessions.filter((s) => s.observed !== null);
  const latest = pick ?? [...observed].reverse().find((s) => s.flagged) ?? observed[observed.length - 1] ?? null;
  const itemCounts = useMemo(() => {
    const m: Record<string, number> = {};
    items.forEach((i) => (m[i.state] = (m[i.state] ?? 0) + 1));
    return m;
  }, [items]);
  const activeAlerts = alerts.filter((a) => ["open", "ack", "assigned"].includes(a.status));

  if (err) return <div className="empty">Centre not found. <Link to="/">Back to overview</Link></div>;
  if (!c) return <div className="empty">Loading…</div>;
  const dev = c.device;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="muted mono" style={{ marginBottom: 2 }}>
            <Link to="/centres">Centres</Link> / {c.code}
          </div>
          <h1>{c.name}</h1>
          <p>
            {c.district}, {c.state} · {c.trade} · {c.scheme} · {c.sanctioned_seats} sanctioned seats{" "}
            {c.simulated ? <span className="tag">synthetic</span> : <span className="tag">AI pipeline</span>}
          </p>
        </div>
        <div className="row">
          <BandChip band={c.risk.band} score={c.risk.score} />
          <a className="btn" href={`${API}/api/v1/centres/${c.code}/brief`} target="_blank" rel="noreferrer">Inspection brief</a>
        </div>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="label">Risk score (0–100)</div>
          <div className="value">{c.risk.score.toFixed(0)}</div>
          <div className="sub">rolling 14 days</div>
        </div>
        <div className="card kpi">
          <div className="label">Sessions flagged</div>
          <div className="value">{flagged}<span className="muted" style={{ fontSize: 16 }}> / {observed.length}</span></div>
          <div className="sub">claimed vs observed beyond tolerance</div>
        </div>
        <div className="card kpi">
          <div className="label">Equipment</div>
          <div className="value">{items.length ? `${itemCounts.present ?? 0}/${items.length}` : "—"}</div>
          <div className="sub">present at last check{itemCounts.candidate_missing ? ` · ${itemCounts.candidate_missing} not found` : ""}</div>
        </div>
        <div className="card kpi">
          <div className="label">Edge device</div>
          <div className="value" style={{ fontSize: 20 }}>{dev ? fmtBytes(dev.bytes_sent) : "—"}</div>
          <div className="sub">
            {dev
              ? `${dev.raw_video_bytes ? `uploaded vs ${fmtBytes(dev.raw_video_bytes)} raw video` : "uploaded (snapshot mode)"} · ${Math.round(dev.uptime_pct * 100)}% uptime · seen ${ago(dev.last_heartbeat)}`
              : "no device data"}
          </div>
        </div>
      </div>

      <div className="tabs" role="tablist">
        {(["attendance", "equipment", "alerts", "privacy"] as Tab[]).map((t) => (
          <button key={t} className={tab === t ? "on" : ""} onClick={() => setTab(t)} role="tab" aria-selected={tab === t}>
            {t === "attendance" ? "Attendance" : t === "equipment" ? `Equipment (${items.length})` : t === "alerts" ? `Alerts (${activeAlerts.length})` : "What leaves the centre"}
          </button>
        ))}
      </div>

      {tab === "attendance" && (
        <div className="grid two">
          <div className="card">
            <div className="card-head">
              <div>
                <h2>Claimed vs observed trainees</h2>
                <p>Each column is a session. Click one to see its evidence.</p>
              </div>
            </div>
            <AttendanceChart rows={sessions} onPick={setPick} />
          </div>
          <div className="grid" style={{ alignContent: "start" }}>
            <div className="card">
              <div className="card-head"><h2>Why this score</h2></div>
              <RiskBreakdown components={c.risk.components} weights={c.risk.weights} />
            </div>
            {latest && (
              <div className="card">
                <div className="card-head">
                  <div>
                    <h2>Session evidence</h2>
                    <p>{latest.batch} · {fmtDateTime(latest.start)}</p>
                  </div>
                  {latest.flagged ? <SeverityChip s="warning" /> : null}
                </div>
                <p style={{ margin: "0 0 10px" }}>
                  Claimed <b>{latest.claimed ?? "—"}</b> · observed <b>{latest.observed ?? "—"}</b> ± {latest.band ?? "—"} over {latest.n_windows} windows
                </p>
                {latest.thumb_ids?.length ? (
                  <div className="thumbs">{latest.thumb_ids.map((t) => <Thumb key={t} id={t} w={150} onOpen={setBig} />)}</div>
                ) : (
                  <p className="muted">{c.simulated ? "Synthetic fleet centre: no imagery." : "No evidence frames for this session."}</p>
                )}
              </div>
            )}
          </div>
          <div className="card" style={{ gridColumn: "1 / -1", overflow: "auto" }}>
            <div className="card-head"><h2>Sessions</h2></div>
            <table>
              <thead><tr><th>Date</th><th>Batch</th><th className="num">Claimed</th><th className="num">Observed</th><th className="num">Gap</th><th>Result</th></tr></thead>
              <tbody>
                {[...sessions].reverse().map((s) => (
                  <tr key={s.session_ref} className="click" onClick={() => setPick(s)}>
                    <td>{fmtDateTime(s.start)}</td>
                    <td>{s.batch}</td>
                    <td className="num">{s.claimed ?? "—"}</td>
                    <td className="num">{s.observed ?? "—"}{s.band !== null ? <span className="muted"> ±{s.band}</span> : null}</td>
                    <td className="num">{s.gap_pct !== null ? `${Math.round(s.gap_pct * 100)}%` : "—"}</td>
                    <td>{s.observed === null ? <span className="muted">camera offline</span> : s.flagged ? <SeverityChip s="warning" /> : <span className="muted">within tolerance</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {tab === "equipment" && (
        <>
          <div className="callout" style={{ marginBottom: 12 }}>
            Each sanctioned item is checked against its registered reference view about twice a day, on the emptiest frame.
            "Not found" must persist for 3 checks over 2 days before an alert. A person standing in front, or a dark room, gives "unverifiable", never "missing".
          </div>
          <div className="grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(250px, 1fr))" }}>
            {items.map((it) => (
              <div key={it.item_key} className="card">
                <div className="row" style={{ justifyContent: "space-between" }}>
                  <div>
                    <b>{it.item_key}</b>
                    <div className="muted" style={{ fontSize: 12 }}>{it.class_name}{it.cam_key ? ` · ${it.cam_key}` : ""}</div>
                  </div>
                  {(() => {
                    if (!it.camera_verifiable) return <ItemChip state="not_checked" />;
                    // mirror the alert rule: an anomaly is only confirmed after 3 consecutive anomalous checks
                    let run = 0;
                    for (let k = it.history.length - 1; k >= 0; k--) {
                      const st = it.history[k].state;
                      if (st === "candidate_missing" || st === "changed") run++;
                      else if (st === "unverifiable" || st === "uncertain") continue;
                      else break;
                    }
                    if ((it.state === "candidate_missing" || it.state === "changed") && run < 3)
                      return <Chip tone="warning" label={`Unconfirmed · re-checking (${run}/3)`} />;
                    return <ItemChip state={it.state} />;
                  })()}
                </div>
                {it.camera_verifiable ? (
                  <>
                    <div style={{ display: "flex", gap: 3, margin: "12px 0 6px" }} aria-label="Check history">
                      {it.history.map((h) => (
                        <span key={h.ts} title={`${fmtDateTime(h.ts)}: ${h.state}${h.sim !== null ? ` (sim ${h.sim})` : ""}`}
                          style={{ flex: 1, height: 14, borderRadius: 3, background: toneColor(itemTone(h.state)), opacity: h.state === "present" ? 0.55 : 1 }} />
                      ))}
                    </div>
                    <div className="muted" style={{ fontSize: 12 }}>
                      Last check {fmtDateTime(it.last_checked)}{it.sim !== null ? ` · similarity ${it.sim}` : ""}
                    </div>
                    {it.usage.length > 0 && (() => {
                      const u = it.usage[it.usage.length - 1];
                      const share = u.observed_min ? u.interaction_min / u.observed_min : 0;
                      return (
                        <div style={{ marginTop: 10 }}>
                          <div className="row" style={{ justifyContent: "space-between", fontSize: 12.5 }}>
                            <span className="secondary">Observed use, last session</span>
                            <span><b>{u.interaction_min}</b><span className="muted"> of {u.observed_min} min</span></span>
                          </div>
                          <div className="bar-track" style={{ marginTop: 4 }}><div className="bar-fill" style={{ width: `${share * 100}%` }} /></div>
                          {u.interaction_min === 0 && <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>No one at this station while trainees were present.</div>}
                        </div>
                      );
                    })()}
                    {it.thumb_id && <div style={{ marginTop: 8 }}><Thumb id={it.thumb_id} w={218} onOpen={setBig} /></div>}
                  </>
                ) : (
                  <p className="muted" style={{ fontSize: 12.5 }}>Not visible to any camera. Verify during physical inspection.</p>
                )}
              </div>
            ))}
            {!items.length && <div className="empty">No sanctioned inventory registered.</div>}
          </div>
        </>
      )}

      {tab === "alerts" && (
        <div className="card" style={{ overflow: "auto" }}>
          <table>
            <thead><tr><th>Severity</th><th>Alert</th><th>Status</th><th>Opened</th></tr></thead>
            <tbody>
              {alerts.map((a) => (
                <tr key={a.id} className="click" onClick={() => setSel(a)}>
                  <td><SeverityChip s={a.severity} /></td>
                  <td>{a.title}</td>
                  <td><StatusChip status={a.status} /></td>
                  <td className="muted">{fmtDateTime(a.opened_at)}</td>
                </tr>
              ))}
              {!alerts.length && <tr><td colSpan={4} className="empty">No alerts for this centre.</td></tr>}
            </tbody>
          </table>
        </div>
      )}

      {tab === "privacy" && <PrivacyPanel centre={c} sessions={sessions} />}

      {sel && <AlertDrawer alert={sel} onClose={() => setSel(null)} onChange={(a) => { setSel(a); setAlerts((r) => r.map((x) => (x.id === a.id ? a : x))); }} />}
      <Lightbox id={big} onClose={() => setBig(null)} />
    </>
  );
}

function PrivacyPanel({ centre, sessions }: { centre: C; sessions: SessionRow[] }) {
  const [sample, setSample] = useState<{ events: unknown[]; bytes_json: number; bytes_gzip: number } | null>(null);
  useEffect(() => {
    fetch(`${API}/api/v1/centres/${centre.code}/payload-sample`).then((r) => r.json()).then(setSample).catch(() => undefined);
  }, [centre.code]);
  const dev = centre.device;
  const thumbs = sessions.flatMap((s) => s.thumb_ids ?? []).slice(0, 1);
  return (
    <div className="grid two">
      <div className="card">
        <div className="card-head">
          <div>
            <h2>The actual data this centre sends</h2>
            <p>Raw video never leaves the centre. The edge device sends counts and states like these, signed and gzip-compressed.</p>
          </div>
        </div>
        {sample ? (
          <>
            <pre className="json">{JSON.stringify(sample.events, null, 2)}</pre>
            <p className="muted" style={{ fontSize: 12.5 }}>
              These {sample.events.length} events: {fmtInt(sample.bytes_json)} bytes as JSON, {fmtInt(sample.bytes_gzip)} bytes on the wire.
            </p>
          </>
        ) : (
          <div className="empty">No events yet.</div>
        )}
      </div>
      <div className="grid" style={{ alignContent: "start" }}>
        <div className="card">
          <h2 style={{ marginBottom: 10 }}>Bandwidth</h2>
          {dev ? (
            <>
              <div className="row" style={{ justifyContent: "space-between" }}><span className="secondary">Uploaded by edge device</span><b>{fmtBytes(dev.bytes_sent)}</b></div>
              <div className="bar-track" style={{ margin: "6px 0 12px" }}><div className="bar-fill" style={{ width: `${Math.max(0.6, (dev.bytes_sent / Math.max(dev.raw_video_bytes, 1)) * 100)}%` }} /></div>
              <div className="row" style={{ justifyContent: "space-between" }}><span className="secondary">Streaming the same video would cost</span><b>{fmtBytes(dev.raw_video_bytes)}</b></div>
              <div className="bar-track" style={{ margin: "6px 0 8px" }}><div className="bar-fill" style={{ width: "100%", background: "var(--text-muted)" }} /></div>
              {dev.raw_video_bytes > 0 && <p className="muted" style={{ fontSize: 12.5 }}>{fmtInt(Math.round(dev.raw_video_bytes / Math.max(dev.bytes_sent, 1)))}× less data. Works on 2G/3G and keeps 14 days of events offline.</p>}
            </>
          ) : <p className="muted">No device data.</p>}
        </div>
        <div className="card">
          <h2 style={{ marginBottom: 8 }}>What is and isn't identified</h2>
          <table>
            <tbody>
              <tr><td>Number of people in the training area</td><td><span className="chip">✓ counted</span></td></tr>
              <tr><td>Whether each sanctioned item is in place</td><td><span className="chip">✓ checked</span></td></tr>
              <tr><td>Camera integrity (looped, frozen, covered, moved)</td><td><span className="chip">✓ checked</span></td></tr>
              <tr><td>Who anyone is / faces</td><td><span className="chip">✗ never</span></td></tr>
              <tr><td>Age, gender or any personal attribute</td><td><span className="chip">✗ never</span></td></tr>
              <tr><td>A person's movements across sessions</td><td><span className="chip">✗ never</span></td></tr>
            </tbody>
          </table>
          {thumbs[0] && (
            <>
              <p className="muted" style={{ fontSize: 12.5, margin: "12px 0 6px" }}>Evidence images are pixelated on the device before upload:</p>
              <Thumb id={thumbs[0]} w={260} />
            </>
          )}
          <p className="muted" style={{ fontSize: 12, marginTop: 10 }}>
            Individual attendance stays with AEBAS; KaushalNetra only cross-checks counts. Aligned with the DPDP Act 2023: purpose limitation, data minimisation, retention limits.
            Last activity {fmtDate(dev?.last_heartbeat ?? null)}.
          </p>
        </div>
      </div>
    </div>
  );
}
