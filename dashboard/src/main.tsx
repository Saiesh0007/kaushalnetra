import { StrictMode, useEffect, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import "./styles.css";
import type { Alert } from "./api";
import { LiveProvider, useLive } from "./components/live";
import { SeverityChip } from "./components/Status";
import { Alerts } from "./pages/Alerts";
import { Centre } from "./pages/Centre";
import { ControlRoom } from "./pages/ControlRoom";
import { Copilot } from "./pages/Copilot";
import { AccuracyLab } from "./pages/AccuracyLab";
import { CentreList, Overview } from "./pages/Overview";

function ThemeToggle() {
  const [theme, setTheme] = useState<string>(() => {
    try {
      return localStorage.getItem("kn-theme") ?? "";
    } catch {
      return "";
    }
  });
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    try {
      localStorage.setItem("kn-theme", theme);
    } catch {
      /* storage unavailable */
    }
  }, [theme]);
  return (
    <select value={theme} onChange={(e) => setTheme(e.target.value)} aria-label="Theme">
      <option value="">System theme</option>
      <option value="light">Light</option>
      <option value="dark">Dark</option>
    </select>
  );
}

function Toasts() {
  const { feed } = useLive();
  const [shown, setShown] = useState<{ a: Alert; at: number }[]>([]);
  const seen = useRef(0);
  useEffect(() => {
    const fresh = feed.filter((m) => m.type === "alert" && m.at > seen.current && m.alert && m.alert.severity !== "info");
    if (fresh.length) {
      seen.current = Math.max(...fresh.map((m) => m.at));
      setShown((s) => [...fresh.slice(0, 3).map((m) => ({ a: m.alert!, at: m.at })), ...s].slice(0, 4));
    }
  }, [feed]);
  useEffect(() => {
    if (!shown.length) return;
    const t = window.setTimeout(() => setShown((s) => s.slice(0, -1)), 7000);
    return () => window.clearTimeout(t);
  }, [shown]);
  return (
    <div className="toasts" aria-live="polite">
      {shown.map(({ a, at }) => (
        <div key={at + a.key} className="toast" style={{ borderLeftColor: a.severity === "critical" ? "var(--critical)" : "var(--warning)" }}>
          <div className="row"><SeverityChip s={a.severity} /><span className="muted" style={{ fontSize: 12 }}>new alert</span></div>
          <div style={{ marginTop: 4, fontWeight: 500 }}>{a.title}</div>
          <div className="muted" style={{ fontSize: 12 }}>{a.centre_name}</div>
        </div>
      ))}
    </div>
  );
}

function Shell() {
  const { connected } = useLive();
  return (
    <div className="app">
      <nav className="side" aria-label="Main">
        <div className="brand">
          <div className="brand-mark" />
          <div>
            <b>KaushalNetra</b>
            <small>Training centre compliance</small>
          </div>
        </div>
        <NavLink to="/" end className="nav">Overview</NavLink>
        <NavLink to="/centres" className="nav">Centres</NavLink>
        <NavLink to="/alerts" className="nav">Alerts</NavLink>
        <NavLink to="/live" className="nav">Control room</NavLink>
        <NavLink to="/copilot" className="nav">Copilot</NavLink>
        <NavLink to="/accuracy" className="nav">Accuracy lab</NavLink>
        <div className="side-foot">
          <span className="row" style={{ gap: 6 }}>
            {connected ? <span className="pulse" /> : <span style={{ width: 8, height: 8, borderRadius: 4, background: "var(--text-muted)" }} />}
            {connected ? "Live updates on" : "Offline: retrying"}
          </span>
          <ThemeToggle />
          <span>Prototype · SIH 2026 · PS 26245</span>
        </div>
      </nav>
      <main className="main">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/centres" element={<CentreList />} />
          <Route path="/centres/:code" element={<Centre />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/live" element={<ControlRoom />} />
          <Route path="/copilot" element={<Copilot />} />
          <Route path="/accuracy" element={<AccuracyLab />} />
        </Routes>
      </main>
      <Toasts />
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <BrowserRouter>
      <LiveProvider>
        <Shell />
      </LiveProvider>
    </BrowserRouter>
  </StrictMode>,
);
