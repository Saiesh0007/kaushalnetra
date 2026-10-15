"""AI Inspector Copilot (Plan.md §A2.10, Memory.md D-013).

The LLM never sees imagery or personal data: it can only call the tools below, which return aggregates.
Provider: any OpenAI-compatible endpoint (Gemini / Groq free tiers, or local Ollama), configured by env:
    KNETRA_LLM_BASE_URL, KNETRA_LLM_API_KEY, KNETRA_LLM_MODEL
Without a provider, a deterministic offline responder answers the common questions (English and Hindi).
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import db as D
from .rules import risk_score, session_attendance

SYSTEM = """You are KaushalNetra Inspector Copilot, assisting monitoring officers of India's Ministry of Skill Development
and Entrepreneurship. You answer ONLY from tool results about training-centre compliance (attendance discrepancies,
equipment checks, camera tampering, risk scores). Rules:
- Always call tools before answering factual questions; never invent centres, numbers or dates.
- Observed counts are privacy-preserving aggregate estimates. Never speculate about individuals, and call gaps
  "discrepancies needing verification", not fraud.
- Reply in the user's language (Hindi if they write in Hindi, otherwise English). Be concise: short bullets, cite centre codes.
- When asked to prepare a visit, give: why the centre is risky, what to check on site, and the brief link /api/v1/centres/<code>/brief.
- Synthetic fleet centres (code KN-SIM-*) are simulated data; say so if relevant."""

TOOLS_SPEC = [
    {"type": "function", "function": {
        "name": "list_centres",
        "description": "Centres ranked by risk score (highest first). Optional filters.",
        "parameters": {"type": "object", "properties": {
            "state": {"type": "string", "description": "Indian state name, e.g. Bihar"},
            "district": {"type": "string"},
            "band": {"type": "string", "enum": ["high", "medium", "low"]},
            "limit": {"type": "integer", "default": 10}}}}},
    {"type": "function", "function": {
        "name": "get_centre",
        "description": "Full compliance picture of one centre: risk breakdown, recent sessions, equipment states, active alerts.",
        "parameters": {"type": "object", "properties": {"code": {"type": "string"}}, "required": ["code"]}}},
    {"type": "function", "function": {
        "name": "list_alerts",
        "description": "Active alerts, most severe first.",
        "parameters": {"type": "object", "properties": {
            "state": {"type": "string"}, "kind": {"type": "string",
            "enum": ["attendance", "over_occupancy", "item_missing", "item_changed", "item_unused", "tamper"]},
            "severity": {"type": "string", "enum": ["critical", "warning", "info"]},
            "limit": {"type": "integer", "default": 15}}}}},
    {"type": "function", "function": {
        "name": "fleet_summary", "description": "National totals: centres, risk bands, open alerts by type, states with most high-risk centres.",
        "parameters": {"type": "object", "properties": {}}}},
]


# ---------------------------------------------------------------- tools (aggregates only)
def _summary(db: Session, c: D.Centre) -> dict:
    r = risk_score(db, c)
    return dict(code=c.code, name=c.name, district=c.district, state=c.state, trade=c.trade, synthetic=c.simulated,
                risk_score=r["score"], risk_band=r["band"], risk_factors=r["components"])


def t_list_centres(db: Session, state: str = "", district: str = "", band: str = "", limit: int = 10) -> list[dict]:
    q = select(D.Centre)
    rows = [c for c in db.scalars(q) if (not state or c.state.lower() == state.lower())
            and (not district or c.district.lower() == district.lower())]
    out = sorted((_summary(db, c) for c in rows), key=lambda x: -x["risk_score"])
    if band:
        out = [x for x in out if x["risk_band"] == band]
    return out[: max(1, min(int(limit or 10), 30))]


def t_get_centre(db: Session, code: str) -> dict:
    c = db.scalar(select(D.Centre).where(D.Centre.code == code.upper().strip()))
    if not c:
        return {"error": f"no centre {code}"}
    att = [dict(date=r["start"].strftime("%Y-%m-%d"), batch=r["batch"], claimed=r["claimed"], observed=r["observed"],
                flagged=r["flagged"]) for r in session_attendance(db, c)][-10:]
    items = []
    for it in db.scalars(select(D.InventoryItem).where(D.InventoryItem.centre_id == c.id)):
        k = db.scalar(select(D.ItemCheck).where(D.ItemCheck.centre_id == c.id, D.ItemCheck.item_key == it.item_key)
                      .order_by(D.ItemCheck.ts.desc()))
        items.append(dict(item=it.item_key, type=it.class_name, last_state=k.state if k else "not_checked",
                          camera_verifiable=it.camera_verifiable))
    alerts = [dict(severity=a.severity, kind=a.kind, title=a.title, status=a.status)
              for a in db.scalars(select(D.Alert).where(D.Alert.centre_id == c.id, D.Alert.status.in_(("open", "ack", "assigned"))))]
    return dict(**_summary(db, c), sanctioned_seats=c.sanctioned_seats, recent_sessions=att,
                equipment_not_present=[i for i in items if i["last_state"] not in ("present", "relocated")],
                equipment_total=len(items), active_alerts=alerts, brief_url=f"/api/v1/centres/{c.code}/brief")


def t_list_alerts(db: Session, state: str = "", kind: str = "", severity: str = "", limit: int = 15) -> list[dict]:
    q = select(D.Alert, D.Centre).join(D.Centre, D.Centre.id == D.Alert.centre_id).where(D.Alert.status.in_(("open", "ack", "assigned")))
    if kind:
        q = q.where(D.Alert.kind == kind)
    if severity:
        q = q.where(D.Alert.severity == severity)
    if state:
        q = q.where(D.Centre.state == state)
    rank = {"critical": 0, "warning": 1, "info": 2}
    rows = sorted(db.execute(q).all(), key=lambda r: (rank.get(r[0].severity, 3), -r[0].opened_at.timestamp()))
    return [dict(centre=c.code, centre_name=c.name, state=c.state, severity=a.severity, kind=a.kind, title=a.title,
                 opened=a.opened_at.strftime("%Y-%m-%d")) for a, c in rows[: max(1, min(int(limit or 15), 40))]]


def t_fleet_summary(db: Session) -> dict:
    cs = db.scalars(select(D.Centre)).all()
    sums = [_summary(db, c) for c in cs]
    by_state: dict[str, int] = {}
    for s in sums:
        if s["risk_band"] == "high":
            by_state[s["state"]] = by_state.get(s["state"], 0) + 1
    kinds: dict[str, int] = {}
    for a in db.scalars(select(D.Alert).where(D.Alert.status.in_(("open", "ack", "assigned")))):
        kinds[a.kind] = kinds.get(a.kind, 0) + 1
    return dict(centres=len(cs), synthetic=sum(c.simulated for c in cs),
                bands={b: sum(s["risk_band"] == b for s in sums) for b in ("high", "medium", "low")},
                open_alerts_by_type=kinds, high_risk_by_state=dict(sorted(by_state.items(), key=lambda x: -x[1])))


TOOLS: dict[str, Callable[..., Any]] = {"list_centres": t_list_centres, "get_centre": t_get_centre,
                                        "list_alerts": t_list_alerts, "fleet_summary": t_fleet_summary}


def call_tool(db: Session, name: str, args: dict) -> Any:
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"unknown tool {name}"}
    try:
        return fn(db, **{k: v for k, v in (args or {}).items() if v not in (None, "")})
    except TypeError as e:
        return {"error": str(e)}


# ---------------------------------------------------------------- LLM loop
def llm_configured() -> bool:
    return bool(os.environ.get("KNETRA_LLM_BASE_URL") and os.environ.get("KNETRA_LLM_MODEL"))


def ask_llm(db: Session, question: str, history: list[dict]) -> dict:
    base = os.environ["KNETRA_LLM_BASE_URL"].rstrip("/")
    headers = {"Authorization": f"Bearer {os.environ.get('KNETRA_LLM_API_KEY', 'none')}"}
    msgs = [{"role": "system", "content": SYSTEM}] + history[-8:] + [{"role": "user", "content": question}]
    trace = []
    with httpx.Client(timeout=90) as client:
        for _ in range(5):
            for attempt in range(3):  # free tiers return 429/503 under load: brief backoff, then give up to offline
                r = client.post(f"{base}/chat/completions", headers=headers, json={
                    "model": os.environ["KNETRA_LLM_MODEL"], "messages": msgs, "tools": TOOLS_SPEC, "temperature": 0.2})
                if r.status_code not in (429, 500, 503):
                    break
                time.sleep(1.5 * (attempt + 1))
            r.raise_for_status()
            m = r.json()["choices"][0]["message"]
            calls = m.get("tool_calls") or []
            if not calls:
                return {"answer": m.get("content") or "", "tool_calls": trace, "mode": "llm"}
            msgs.append({"role": "assistant", "content": m.get("content") or "", "tool_calls": calls})
            for tc in calls:
                args = json.loads(tc["function"].get("arguments") or "{}")
                trace.append({"name": tc["function"]["name"], "args": args})
                result = call_tool(db, tc["function"]["name"], args)
                msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(result, default=str)[:12000]})
    return {"answer": "I could not complete that request.", "tool_calls": trace, "mode": "llm"}


# ---------------------------------------------------------------- offline fallback
HI = re.compile(r"[ऀ-ॿ]")
STATE_HI = {"बिहार": "Bihar", "महाराष्ट्र": "Maharashtra", "उत्तर प्रदेश": "Uttar Pradesh", "राजस्थान": "Rajasthan",
            "गुजरात": "Gujarat", "मध्य प्रदेश": "Madhya Pradesh", "कर्नाटक": "Karnataka", "तमिलनाडु": "Tamil Nadu",
            "पश्चिम बंगाल": "West Bengal", "तेलंगाना": "Telangana", "ओडिशा": "Odisha", "झारखंड": "Jharkhand", "केरल": "Kerala",
            "असम": "Assam", "पंजाब": "Punjab", "उत्तराखंड": "Uttarakhand", "छत्तीसगढ़": "Chhattisgarh", "आंध्र प्रदेश": "Andhra Pradesh"}
CITY_HI = {"पुणे": "Pune", "पटना": "Patna", "लखनऊ": "Lucknow", "नागपुर": "Nagpur", "जयपुर": "Jaipur", "इंदौर": "Indore"}


def ask_offline(db: Session, question: str) -> dict:
    hi = bool(HI.search(question))
    q = question.lower()
    trace: list[dict] = []
    states = {c.state for c in db.scalars(select(D.Centre))}
    districts = {c.district for c in db.scalars(select(D.Centre))}
    state = next((s for s in states if s.lower() in q), "") or next((v for k, v in STATE_HI.items() if k in question), "")
    district = next((d for d in districts if d and d.lower() in q), "") or next((v for k, v in CITY_HI.items() if k in question), "")
    code = re.search(r"kn-[a-z]+-\d+|kn-demo-[a-d]", q)

    if code:
        args = {"code": code.group(0).upper()}
        trace.append({"name": "get_centre", "args": args})
        c = t_get_centre(db, **args)
        if "error" in c:
            return {"answer": c["error"], "tool_calls": trace, "mode": "offline"}
        lines = [f"**{c['name']} ({c['code']})**: {c['district']}, {c['state']}",
                 (f"जोखिम स्कोर {c['risk_score']:.0f}/100 ({c['risk_band']})" if hi else f"Risk {c['risk_score']:.0f}/100 ({c['risk_band']})")]
        flagged = [s for s in c["recent_sessions"] if s["flagged"]]
        if flagged:
            s = flagged[-1]
            lines.append((f"- उपस्थिति: {len(flagged)} सत्रों में अंतर; अंतिम: दावा {s['claimed']}, देखा गया {s['observed']}" if hi else
                          f"- Attendance: {len(flagged)} flagged sessions; latest claimed {s['claimed']} vs observed {s['observed']}"))
        if c["equipment_not_present"]:
            lines.append((f"- उपकरण जाँचें: " if hi else "- Check equipment: ") + ", ".join(f"{i['item']} ({i['last_state']})" for i in c["equipment_not_present"][:6]))
        for a in c["active_alerts"][:5]:
            lines.append(f"- [{a['severity']}] {a['title']}")
        lines.append((f"निरीक्षण ब्रीफ: {c['brief_url']}" if hi else f"Inspection brief: {c['brief_url']}"))
        return {"answer": "\n".join(lines), "tool_calls": trace, "mode": "offline"}

    if any(w in q for w in ("tamper", "camera", "loop", "frozen", "covered")) or any(w in question for w in ("कैमरा", "छेड़छाड़")):
        args = {"kind": "tamper", "state": state}
        trace.append({"name": "list_alerts", "args": args})
        rows = t_list_alerts(db, **args)
        head = "कैमरा छेड़छाड़ अलर्ट:" if hi else "Camera tampering alerts:"
        return {"answer": head + "\n" + ("\n".join(f"- {r['centre']} {r['centre_name']} ({r['state']}): {r['title']}" for r in rows) or "- none"),
                "tool_calls": trace, "mode": "offline"}

    if any(w in q for w in ("equipment", "missing", "machine", "monitor")) or "उपकरण" in question:
        args = {"kind": "item_missing", "state": state}
        trace.append({"name": "list_alerts", "args": args})
        rows = t_list_alerts(db, **args)
        head = "गायब उपकरण अलर्ट:" if hi else "Missing-equipment alerts:"
        return {"answer": head + "\n" + ("\n".join(f"- {r['centre']} ({r['state']}): {r['title']}" for r in rows) or "- none"),
                "tool_calls": trace, "mode": "offline"}

    if any(w in q for w in ("summary", "overall", "national", "how many")) or "कुल" in question:
        trace.append({"name": "fleet_summary", "args": {}})
        s = t_fleet_summary(db)
        top = ", ".join(f"{k} ({v})" for k, v in list(s["high_risk_by_state"].items())[:4]) or "—"
        ans = (f"{s['centres']} केंद्र ({s['synthetic']} कृत्रिम) · उच्च जोखिम {s['bands']['high']}, मध्यम {s['bands']['medium']}\n"
               f"सबसे अधिक उच्च-जोखिम राज्य: {top}" if hi else
               f"{s['centres']} centres ({s['synthetic']} synthetic) · {s['bands']['high']} high risk, {s['bands']['medium']} medium\n"
               f"States with most high-risk centres: {top}\nOpen alerts: " + ", ".join(f"{k} {v}" for k, v in s["open_alerts_by_type"].items()))
        return {"answer": ans, "tool_calls": trace, "mode": "offline"}

    args = {"state": state, "district": district, "limit": 5}
    trace.append({"name": "list_centres", "args": {k: v for k, v in args.items() if v}})
    rows = t_list_centres(db, **args)
    where = district or state or ("देश" if hi else "the country")
    head = f"{where} में सबसे अधिक जोखिम वाले केंद्र:" if hi else f"Highest-risk centres in {where}:"
    body = "\n".join(f"- {r['code']} {r['name']} ({r['district']}): {r['risk_score']:.0f}/100 {r['risk_band']}"
                     + (" · synthetic" if r["synthetic"] else "") for r in rows) or "- none"
    return {"answer": head + "\n" + body, "tool_calls": trace, "mode": "offline"}


def ask(db: Session, question: str, history: list[dict] | None = None) -> dict:
    if llm_configured():
        try:
            return ask_llm(db, question, history or [])
        except (httpx.HTTPError, KeyError, ValueError) as e:
            out = ask_offline(db, question)
            out["note"] = f"LLM unavailable ({type(e).__name__}); answered offline"
            return out
    return ask_offline(db, question)
