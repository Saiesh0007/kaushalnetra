import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { API } from "../api";

interface Turn {
  role: "user" | "assistant";
  content: string;
  tool_calls?: { name: string; args: Record<string, unknown> }[];
  mode?: string;
  note?: string;
}

const SUGGEST = [
  "Which centres are highest risk right now?",
  "Brief me before visiting KN-DEMO-B",
  "Any camera tampering this week?",
  "Show missing-equipment alerts",
  "बिहार में कौन से केंद्र जोखिम में हैं?",
  "कुल स्थिति का सारांश दें",
];

function Rich({ text }: { text: string }) {
  // tiny renderer: **bold**, bullet lines, centre codes and brief links become links
  return (
    <>
      {text.split("\n").map((line, i) => {
        const parts = line.split(/(\*\*[^*]+\*\*|KN-[A-Z]+-[0-9A-D]+|\/api\/v1\/centres\/[A-Z0-9-]+\/brief)/g);
        return (
          <div key={i} style={{ paddingLeft: line.startsWith("- ") ? 12 : 0, minHeight: 4 }}>
            {parts.map((p, j) =>
              p.startsWith("**") ? <b key={j}>{p.slice(2, -2)}</b>
              : /^KN-[A-Z]+-[0-9A-D]+$/.test(p) ? <Link key={j} to={`/centres/${p}`}>{p}</Link>
              : p.startsWith("/api/v1/") ? <a key={j} href={API + p} target="_blank" rel="noreferrer">open brief</a>
              : <span key={j}>{line.startsWith("- ") && j === 0 ? "• " + p.slice(2) : p}</span>,
            )}
          </div>
        );
      })}
    </>
  );
}

export function Copilot() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => end.current?.scrollIntoView({ behavior: "smooth" }), [turns]);

  const send = async (question: string) => {
    if (!question.trim() || busy) return;
    const history = turns.map(({ role, content }) => ({ role, content }));
    setTurns((t) => [...t, { role: "user", content: question }]);
    setQ("");
    setBusy(true);
    try {
      const r = await fetch(`${API}/api/v1/copilot`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ question, history }),
      });
      const d = await r.json();
      setTurns((t) => [...t, { role: "assistant", content: d.answer, tool_calls: d.tool_calls, mode: d.mode, note: d.note }]);
    } catch (e) {
      setTurns((t) => [...t, { role: "assistant", content: `Could not reach the server: ${String(e)}` }]);
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inspector Copilot</h1>
          <p>Ask in English or Hindi. The copilot reads aggregate compliance data only: no images, no personal data.</p>
        </div>
      </div>
      <div className="card" style={{ display: "flex", flexDirection: "column", minHeight: 520 }}>
        <div style={{ flex: 1, overflow: "auto", display: "flex", flexDirection: "column", gap: 12, paddingBottom: 8 }}>
          {!turns.length && (
            <div className="empty" style={{ textAlign: "left" }}>
              <p style={{ marginTop: 0 }}>Try one of these:</p>
              <div className="row">{SUGGEST.map((s) => <button key={s} className="btn" onClick={() => send(s)}>{s}</button>)}</div>
            </div>
          )}
          {turns.map((t, i) => (
            <div key={i} style={{ alignSelf: t.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%" }}>
              <div style={{
                background: t.role === "user" ? "var(--accent)" : "var(--surface-2)",
                color: t.role === "user" ? "#fff" : "var(--text-primary)",
                borderRadius: 12, padding: "10px 14px",
              }}>
                {t.role === "user" ? t.content : <Rich text={t.content} />}
              </div>
              {t.tool_calls && t.tool_calls.length > 0 && (
                <div className="muted" style={{ fontSize: 11.5, marginTop: 4 }}>
                  Looked up: {t.tool_calls.map((c) => `${c.name}(${Object.entries(c.args).map(([k, v]) => `${k}=${v}`).join(", ")})`).join(" → ")}
                  {t.mode === "offline" ? " · offline mode" : t.mode === "llm" ? " · LLM" : ""}
                  {t.note ? ` · ${t.note}` : ""}
                </div>
              )}
            </div>
          ))}
          {busy && <div className="muted">Looking up compliance data…</div>}
          <div ref={end} />
        </div>
        <form className="row" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }} onSubmit={(e) => { e.preventDefault(); void send(q); }}>
          <input style={{ flex: 1 }} placeholder="e.g. Which centres in Uttar Pradesh need a visit?" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" />
          <button className="btn primary" disabled={busy || !q.trim()}>Ask</button>
        </form>
      </div>
    </>
  );
}
