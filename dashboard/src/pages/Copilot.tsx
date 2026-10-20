import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Link } from "react-router-dom";
import { API } from "../api";

interface Turn {
  role: "user" | "assistant";
  content: string;
  tool_calls?: { name: string; args: Record<string, unknown> }[];
  mode?: string;
  note?: string;
}

// Conversation lives outside the component so it survives page switches,
// and in sessionStorage so it survives a refresh of the tab.
const KEY = "kn.copilot.turns";
function load(): Turn[] {
  try {
    return JSON.parse(sessionStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}
let chat: { turns: Turn[]; busy: boolean } = { turns: load(), busy: false };
const subs = new Set<() => void>();
function setChat(next: Partial<typeof chat>) {
  chat = { ...chat, ...next };
  try {
    sessionStorage.setItem(KEY, JSON.stringify(chat.turns));
  } catch {
    /* storage unavailable: keep in memory only */
  }
  subs.forEach((f) => f());
}
function subscribe(f: () => void) {
  subs.add(f);
  return () => {
    subs.delete(f);
  };
}
const addTurn = (t: Turn) => setChat({ turns: [...chat.turns, t] });

async function send(question: string) {
  if (!question.trim() || chat.busy) return;
  const history = chat.turns.map(({ role, content }) => ({ role, content }));
  addTurn({ role: "user", content: question });
  setChat({ busy: true });
  try {
    const r = await fetch(`${API}/api/v1/copilot`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ question, history }),
    });
    const d = await r.json();
    addTurn({ role: "assistant", content: d.answer, tool_calls: d.tool_calls, mode: d.mode, note: d.note });
  } catch (e) {
    addTurn({ role: "assistant", content: `Could not reach the server: ${String(e)}` });
  } finally {
    setChat({ busy: false });
  }
}

const SUGGEST = [
  "Which centres are highest risk right now?",
  "Brief me before visiting KN-DEMO-B",
  "Any camera tampering this week?",
  "Show missing-equipment alerts",
  "बिहार में कौन से केंद्र जोखिम में हैं?",
  "कुल स्थिति का सारांश दें",
];

function Inline({ text }: { text: string }) {
  // **bold**, `code`, centre codes -> links, brief paths -> links
  const parts = text.split(/(\*\*[^*]+\*\*|`[^`]+`|KN-[A-Z]+-[0-9A-E]+|\/api\/v1\/centres\/[A-Z0-9-]+\/brief)/g);
  return (
    <>
      {parts.map((p, j) => {
        if (p.startsWith("**") && p.endsWith("**")) return <b key={j}><Inline text={p.slice(2, -2)} /></b>;
        if (p.startsWith("`") && p.endsWith("`")) return <Inline key={j} text={p.slice(1, -1)} />;
        if (/^KN-[A-Z]+-[0-9A-E]+$/.test(p)) return <Link key={j} to={`/centres/${p}`}>{p}</Link>;
        if (/^\/api\/v1\/centres\/[A-Z0-9-]+\/brief$/.test(p)) return <a key={j} href={API + p} target="_blank" rel="noreferrer">open inspection brief</a>;
        return <span key={j}>{p}</span>;
      })}
    </>
  );
}

function Rich({ text }: { text: string }) {
  // small markdown subset: headings, bullets (nested by indent), rules, paragraphs
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 3 }}>
      {text.split("\n").map((raw, i) => {
        const indent = raw.length - raw.trimStart().length;
        const line = raw.trim();
        if (!line) return <div key={i} style={{ height: 4 }} />;
        if (/^-{3,}$/.test(line)) return <hr key={i} style={{ border: 0, borderTop: "1px solid var(--border)", width: "100%", margin: "4px 0" }} />;
        const h = line.match(/^(#{1,4})\s+(.*)$/);
        if (h) return <div key={i} style={{ fontWeight: 600, marginTop: 6 }}><Inline text={h[2]} /></div>;
        const b = line.match(/^([*-]|\d+\.)\s+(.*)$/);
        if (b)
          return (
            <div key={i} style={{ display: "flex", gap: 6, paddingLeft: 4 + Math.min(indent, 8) * 6 }}>
              <span className="muted">{/^\d/.test(b[1]) ? b[1] : "•"}</span>
              <span><Inline text={b[2]} /></span>
            </div>
          );
        return <div key={i}><Inline text={line} /></div>;
      })}
    </div>
  );
}

export function Copilot() {
  const { turns, busy } = useSyncExternalStore(subscribe, () => chat);
  const [q, setQ] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns]);

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Inspector Copilot</h1>
          <p>Ask in English or Hindi. The copilot reads aggregate compliance data only: no images, no personal data.</p>
        </div>
        {turns.length > 0 && (
          <button className="btn" disabled={busy} onClick={() => setChat({ turns: [] })}>New chat</button>
        )}
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
        <form className="row" style={{ borderTop: "1px solid var(--border)", paddingTop: 12 }} onSubmit={(e) => { e.preventDefault(); if (busy) return; void send(q); setQ(""); }}>
          <input style={{ flex: 1 }} placeholder="e.g. Which centres in Uttar Pradesh need a visit?" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Question" />
          <button className="btn primary" disabled={busy || !q.trim()}>Ask</button>
        </form>
      </div>
    </>
  );
}
