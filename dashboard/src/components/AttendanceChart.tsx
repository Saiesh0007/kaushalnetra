import { useMemo, useRef, useState } from "react";
import { fmtDate, type SessionRow } from "../api";

/**
 * Claimed vs observed per session (dumbbell). One y-axis (trainees).
 * Observed = filled series-1 dot with its tolerance band; claimed = hollow ring; the connector turns
 * critical when the session is flagged. Hover a session for exact values.
 */
export function AttendanceChart({ rows, onPick, height = 260 }: { rows: SessionRow[]; onPick?: (r: SessionRow) => void; height?: number }) {
  const data = rows.filter((r) => r.observed !== null || r.claimed !== null);
  const wrap = useRef<HTMLDivElement>(null);
  const [hover, setHover] = useState<number | null>(null);
  const W = 760;
  const H = height;
  const m = { l: 40, r: 16, t: 14, b: 34 };
  const iw = W - m.l - m.r;
  const ih = H - m.t - m.b;

  const [yMax, ticks] = useMemo(() => {
    const v = Math.max(1, ...data.map((r) => Math.max(r.claimed ?? 0, (r.observed ?? 0) + (r.band ?? 0))));
    const step = [1, 2, 5, 10, 20, 25, 50, 100].find((s) => (v * 1.1) / s <= 5) ?? 100;
    const top = Math.ceil((v * 1.1) / step) * step;
    return [top, Array.from({ length: top / step + 1 }, (_, i) => i * step)] as const;
  }, [data]);

  if (!data.length) return <div className="empty">No sessions observed yet.</div>;
  const x = (i: number) => m.l + (data.length === 1 ? iw / 2 : (iw * (i + 0.5)) / data.length);
  const y = (v: number) => m.t + ih - (v / yMax) * ih;
  const slot = iw / data.length;
  const labelEvery = Math.ceil(data.length / 12);
  const h = hover !== null ? data[hover] : null;

  return (
    <div ref={wrap} style={{ position: "relative" }}>
      <div className="legend" style={{ marginBottom: 6 }}>
        <span>
          <svg width="12" height="12"><circle cx="6" cy="6" r="4.5" fill="var(--series-1)" /></svg>Observed (edge AI)
        </span>
        <span>
          <svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="var(--surface-1)" stroke="var(--text-primary)" strokeWidth="2" /></svg>
          Claimed (centre MIS)
        </span>
        <span>
          <svg width="14" height="10"><rect width="14" height="10" rx="2" fill="var(--band)" /></svg>Tolerance band
        </span>
        <span>
          <svg width="16" height="4"><rect width="16" height="2" y="1" fill="var(--critical)" /></svg>Flagged gap
        </span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" role="img" aria-label="Claimed versus observed attendance per session">
        {ticks.map((t) => (
          <g key={t}>
            <line x1={m.l} x2={W - m.r} y1={y(t)} y2={y(t)} stroke="var(--grid)" strokeWidth={1} />
            <text x={m.l - 8} y={y(t) + 4} textAnchor="end" fontSize="11" fill="var(--text-muted)">{t}</text>
          </g>
        ))}
        {data.map((r, i) => {
          const cx = x(i);
          const flagged = r.flagged;
          return (
            <g key={r.session_ref} onMouseEnter={() => setHover(i)} onMouseLeave={() => setHover(null)} onClick={() => onPick?.(r)} style={{ cursor: onPick ? "pointer" : "default" }}>
              <rect x={cx - slot / 2} y={m.t} width={slot} height={ih} fill={hover === i ? "var(--surface-2)" : "transparent"} />
              {r.observed !== null && r.band !== null && (
                <rect x={cx - 7} y={y(r.observed + r.band)} width={14} height={Math.max(2, y(Math.max(0, r.observed - r.band)) - y(r.observed + r.band))} rx={4} fill="var(--band)" />
              )}
              {r.observed !== null && r.claimed !== null && (
                <line x1={cx} x2={cx} y1={y(r.observed)} y2={y(r.claimed)} stroke={flagged ? "var(--critical)" : "var(--text-muted)"} strokeWidth={2} strokeLinecap="round" />
              )}
              {r.claimed !== null && <circle cx={cx} cy={y(r.claimed)} r={5} fill="var(--surface-1)" stroke="var(--text-primary)" strokeWidth={2} />}
              {r.observed !== null && <circle cx={cx} cy={y(r.observed)} r={5.5} fill="var(--series-1)" stroke="var(--surface-1)" strokeWidth={2} />}
              {i % labelEvery === 0 && (
                <text x={cx} y={H - 12} textAnchor="middle" fontSize="11" fill="var(--text-muted)">
                  {fmtDate(r.start)}
                </text>
              )}
            </g>
          );
        })}
        <line x1={m.l} x2={W - m.r} y1={y(0)} y2={y(0)} stroke="var(--border)" strokeWidth={1} />
      </svg>
      {h && hover !== null && (
        <div className="chart-tip" style={{ left: `${(x(hover) / W) * 100}%`, top: 24, transform: "translateX(-50%)" }}>
          <b>{h.batch || h.session_ref}</b> · {fmtDate(h.start)}
          <br />
          Claimed <b>{h.claimed ?? "—"}</b> · Observed <b>{h.observed ?? "—"}</b>
          {h.band !== null && <> ± {h.band}</>}
          <br />
          {h.flagged ? (
            <span style={{ color: "var(--critical-text)" }}>Flagged: gap {h.gap} ({Math.round((h.gap_pct ?? 0) * 100)}%)</span>
          ) : (
            <span className="muted">Within tolerance</span>
          )}
        </div>
      )}
    </div>
  );
}

export function RiskBreakdown({ components, weights }: { components: Record<string, number>; weights: Record<string, number> }) {
  const labels: Record<string, string> = {
    attendance: "Attendance gap",
    infra: "Equipment missing / changed",
    usage: "Equipment unused",
    tamper: "Camera tampering",
    uptime: "Camera downtime",
  };
  return (
    <div className="grid" style={{ gap: 10 }}>
      {Object.keys(weights).map((k) => {
        const sev = components[k] ?? 0;
        return (
          <div key={k}>
            <div className="row" style={{ justifyContent: "space-between", fontSize: 12.5 }}>
              <span className="secondary">{labels[k] ?? k}</span>
              <span>
                <b>{Math.round(sev * 100)}%</b>
                <span className="muted"> severity · weight {weights[k]}</span>
              </span>
            </div>
            <div className="bar-track">
              <div className="bar-fill" style={{ width: `${sev * 100}%` }} />
            </div>
          </div>
        );
      })}
      <p className="muted" style={{ fontSize: 12, margin: 0 }}>
        Score = 100 × (1 − Π(1 − weight × severity)). One serious issue is enough for high risk; smaller issues add up.
      </p>
    </div>
  );
}
