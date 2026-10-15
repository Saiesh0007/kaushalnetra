import type { Band, Severity } from "../api";

/* Status colours never carry meaning alone: every chip pairs colour + icon + label. */
type Tone = "good" | "warning" | "serious" | "critical" | "neutral" | "info";

const COLOR: Record<Tone, string> = {
  good: "var(--good)",
  warning: "var(--warning)",
  serious: "var(--serious)",
  critical: "var(--critical)",
  neutral: "var(--text-muted)",
  info: "var(--accent)",
};

function Icon({ tone }: { tone: Tone }) {
  const c = COLOR[tone];
  switch (tone) {
    case "good":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <circle cx="6" cy="6" r="6" fill={c} />
          <path d="M3.3 6.2l1.8 1.7 3.6-3.8" stroke="#fff" strokeWidth="1.5" fill="none" strokeLinecap="round" />
        </svg>
      );
    case "critical":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <circle cx="6" cy="6" r="6" fill={c} />
          <path d="M4 4l4 4M8 4l-4 4" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
    case "warning":
    case "serious":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <path d="M6 0.6L11.6 11H0.4z" fill={c} />
          <path d="M6 4.3v3" stroke="#000" strokeWidth="1.4" strokeLinecap="round" />
          <circle cx="6" cy="9" r="0.8" fill="#000" />
        </svg>
      );
    case "info":
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <circle cx="6" cy="6" r="6" fill={c} />
          <path d="M6 5.3v3.3" stroke="#fff" strokeWidth="1.5" strokeLinecap="round" />
          <circle cx="6" cy="3.4" r="0.85" fill="#fff" />
        </svg>
      );
    default:
      return (
        <svg width="12" height="12" viewBox="0 0 12 12" aria-hidden>
          <circle cx="6" cy="6" r="5" fill="none" stroke={c} strokeWidth="1.5" />
          <path d="M3.5 6h5" stroke={c} strokeWidth="1.5" strokeLinecap="round" />
        </svg>
      );
  }
}

export function Chip({ tone, label, title }: { tone: Tone; label: string; title?: string }) {
  return (
    <span className="chip" title={title}>
      <Icon tone={tone} />
      {label}
    </span>
  );
}

export const BAND_TONE: Record<Band, Tone> = { low: "good", medium: "warning", high: "critical" };
export const BandChip = ({ band, score }: { band: Band; score?: number }) => (
  <Chip tone={BAND_TONE[band]} label={`${band[0].toUpperCase()}${band.slice(1)} risk${score !== undefined ? ` · ${score.toFixed(0)}` : ""}`} />
);

const SEV_TONE: Record<Severity, Tone> = { critical: "critical", warning: "warning", info: "info" };
export const SeverityChip = ({ s }: { s: Severity }) => <Chip tone={SEV_TONE[s]} label={s[0].toUpperCase() + s.slice(1)} />;

const ITEM: Record<string, [Tone, string]> = {
  present: ["good", "Present"],
  candidate_missing: ["critical", "Not found"],
  changed: ["serious", "Changed / covered"],
  relocated: ["warning", "Relocated"],
  uncertain: ["neutral", "Uncertain"],
  unverifiable: ["neutral", "Unverifiable"],
  not_checked: ["neutral", "Not checked"],
};
export const itemTone = (s: string): Tone => (ITEM[s] ?? ["neutral", s])[0];
export const ItemChip = ({ state }: { state: string }) => {
  const [t, l] = ITEM[state] ?? ["neutral", state];
  return <Chip tone={t} label={l} />;
};
export const toneColor = (t: Tone) => COLOR[t];

const STATUS: Record<string, [Tone, string]> = {
  open: ["critical", "Open"],
  ack: ["warning", "Acknowledged"],
  assigned: ["info", "Assigned"],
  resolved: ["good", "Resolved"],
  dismissed: ["neutral", "Dismissed"],
};
export const StatusChip = ({ status }: { status: string }) => {
  const [t, l] = STATUS[status] ?? ["neutral", status];
  return <Chip tone={t} label={l} />;
};
