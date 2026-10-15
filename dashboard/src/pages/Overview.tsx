import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, fmtBytes, fmtInt, type Centre, type Stats } from "../api";
import { IndiaMap } from "../components/IndiaMap";
import { useLive } from "../components/live";
import { BandChip, Chip } from "../components/Status";

export function Overview() {
  const { version } = useLive();
  const [stats, setStats] = useState<Stats | null>(null);
  const [centres, setCentres] = useState<Centre[]>([]);
  const [scope, setScope] = useState<"all" | "real">("all");
  const nav = useNavigate();

  useEffect(() => {
    api.stats().then(setStats).catch(() => undefined);
    api.centres().then(setCentres).catch(() => undefined);
  }, [version]);

  const shown = scope === "real" ? centres.filter((c) => !c.simulated) : centres;
  const crit = stats?.open_alerts.critical ?? 0;
  const warn = stats?.open_alerts.warning ?? 0;

  return (
    <>
      <div className="page-head">
        <div>
          <h1>National overview</h1>
          <p>Training centres ranked by compliance risk, from edge-AI camera analysis. No faces, counts only.</p>
        </div>
        <div className="seg" role="tablist" aria-label="Centre scope">
          <button className={scope === "all" ? "on" : ""} onClick={() => setScope("all")}>All centres</button>
          <button className={scope === "real" ? "on" : ""} onClick={() => setScope("real")}>AI-pipeline centres only</button>
        </div>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="label">Centres monitored</div>
          <div className="value">{stats ? fmtInt(stats.centres) : "—"}</div>
          <div className="sub">{stats ? `${stats.real_centres} through the AI pipeline · ${stats.centres - stats.real_centres} synthetic` : ""}</div>
        </div>
        <div className="card kpi">
          <div className="label">High-risk centres</div>
          <div className="value">{stats?.bands.high ?? "—"}</div>
          <div className="sub">{stats ? `${stats.bands.medium} medium · ${stats.bands.low} low` : ""}</div>
        </div>
        <div className="card kpi">
          <div className="label">Open alerts</div>
          <div className="value">{crit + warn}</div>
          <div className="sub row" style={{ gap: 6 }}>
            <Chip tone="critical" label={`${crit} critical`} />
            <Chip tone="warning" label={`${warn} warning`} />
          </div>
        </div>
        <div className="card kpi">
          <div className="label">Bandwidth (AI-pipeline centres)</div>
          <div className="value">{stats ? fmtBytes(stats.pipeline_bytes_sent) : "—"}</div>
          <div className="sub">
            uploaded instead of {stats ? fmtBytes(stats.pipeline_raw_video_bytes) : "—"} of video
            {stats && stats.pipeline_bytes_sent ? ` · ${fmtInt(Math.round(stats.pipeline_raw_video_bytes / stats.pipeline_bytes_sent))}× less` : ""}
          </div>
        </div>
      </div>

      <div className="grid two" style={{ marginTop: 14 }}>
        <div className="card">
          <div className="card-head">
            <div>
              <h2>Centre risk map</h2>
              <p>Click a centre to open it. Larger dots: centres processed by the AI pipeline. Smaller: synthetic fleet.</p>
            </div>
            <div className="legend">
              <span><Chip tone="critical" label="High" /></span>
              <span><Chip tone="warning" label="Medium" /></span>
              <span><Chip tone="good" label="Low" /></span>
            </div>
          </div>
          <IndiaMap centres={shown} />
        </div>
        <div className="card" style={{ display: "flex", flexDirection: "column" }}>
          <div className="card-head">
            <div>
              <h2>Inspect first</h2>
              <p>Highest risk score over the last 14 days</p>
            </div>
            <Link to="/centres">All centres →</Link>
          </div>
          <div style={{ overflow: "auto", maxHeight: 440 }}>
            <table>
              <thead>
                <tr><th>Centre</th><th>Risk</th><th className="num">Alerts</th></tr>
              </thead>
              <tbody>
                {shown.slice(0, 14).map((c) => (
                  <tr key={c.code} className="click" onClick={() => nav(`/centres/${c.code}`)}>
                    <td>
                      <div style={{ fontWeight: 500 }}>{c.name}</div>
                      <div className="muted" style={{ fontSize: 12 }}>
                        {c.district}, {c.state} · {c.trade} {c.simulated ? "" : <span className="tag">AI pipeline</span>}
                      </div>
                    </td>
                    <td><BandChip band={c.risk.band} score={c.risk.score} /></td>
                    <td className="num">{c.open_alerts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </>
  );
}

export function CentreList() {
  const { version } = useLive();
  const [centres, setCentres] = useState<Centre[]>([]);
  const [q, setQ] = useState("");
  const [band, setBand] = useState("");
  const nav = useNavigate();
  useEffect(() => {
    api.centres().then(setCentres).catch(() => undefined);
  }, [version]);
  const rows = centres.filter(
    (c) => (!band || c.risk.band === band) && (`${c.name} ${c.code} ${c.district} ${c.state} ${c.trade}`.toLowerCase().includes(q.toLowerCase())),
  );
  return (
    <>
      <div className="page-head">
        <div>
          <h1>Centres</h1>
          <p>{rows.length} of {centres.length} centres</p>
        </div>
        <div className="row">
          <input placeholder="Search name, district, trade…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Search centres" />
          <select value={band} onChange={(e) => setBand(e.target.value)} aria-label="Risk band">
            <option value="">All risk bands</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
        </div>
      </div>
      <div className="card" style={{ overflow: "auto" }}>
        <table>
          <thead>
            <tr><th>Centre</th><th>Location</th><th>Trade</th><th>Risk</th><th className="num">Open alerts</th><th className="num">Seats</th><th>Source</th></tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr key={c.code} className="click" onClick={() => nav(`/centres/${c.code}`)}>
                <td><b style={{ fontWeight: 500 }}>{c.name}</b><div className="muted mono">{c.code}</div></td>
                <td>{c.district}, {c.state}</td>
                <td>{c.trade}</td>
                <td><BandChip band={c.risk.band} score={c.risk.score} /></td>
                <td className="num">{c.open_alerts}</td>
                <td className="num">{c.sanctioned_seats}</td>
                <td>{c.simulated ? <span className="tag">synthetic</span> : <span className="tag">AI pipeline</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
