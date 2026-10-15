"""Drishti central server: ingest, registry, rules, REST API and live WebSocket (Architecture.md §3.2, Design.md §11)."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import os
import re
from datetime import datetime

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Query, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from common import schemas as S

from . import db as D
from .rules import evaluate_centre, risk_score, session_attendance

EDGE_SECRET = os.environ.get("DRISHTI_EDGE_SECRET", "dev-secret").encode()
THUMB_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

app = FastAPI(title="Drishti API", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    D.init_db()


def get_db():
    db = D.SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ---------------------------------------------------------------- live push
class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()

    async def broadcast(self, msg: dict) -> None:
        dead = []
        for ws in self.clients:
            try:
                await ws.send_json(msg)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)


hub = Hub()


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()
    hub.clients.add(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        hub.clients.discard(ws)


# ---------------------------------------------------------------- serialisers
def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() + "Z" if dt else None


def alert_json(a: D.Alert, centre: D.Centre | None = None) -> dict:
    return dict(id=a.id, key=a.key, centre_id=a.centre_id, centre_code=centre.code if centre else None,
                centre_name=centre.name if centre else None, kind=a.kind, severity=a.severity, status=a.status,
                title=a.title, detail=a.detail, evidence=a.evidence, opened_at=iso(a.opened_at), updated_at=iso(a.updated_at),
                assignee=a.assignee, resolution_note=a.resolution_note)


def centre_by_code(db: Session, code: str) -> D.Centre:
    c = db.scalar(select(D.Centre).where(D.Centre.code == code))
    if not c:
        raise HTTPException(404, f"centre {code} not found")
    return c


# ---------------------------------------------------------------- registry
@app.get("/api/v1/health")
def health() -> dict:
    return {"ok": True, "time": iso(D.now())}


def upsert_centre(db: Session, spec: S.CentreSpec) -> D.Centre:
    c = db.scalar(select(D.Centre).where(D.Centre.code == spec.code))
    fields = spec.model_dump(exclude={"cameras", "items"})
    if c is None:
        c = D.Centre(**fields)
        db.add(c)
        db.flush()
    else:
        for k, v in fields.items():
            setattr(c, k, v)
    for cam in spec.cameras:
        row = db.scalar(select(D.Camera).where(D.Camera.centre_id == c.id, D.Camera.cam_key == cam.id))
        if row is None:
            db.add(D.Camera(centre_id=c.id, cam_key=cam.id, name=cam.name, coverage=cam.coverage, mode=cam.mode))
        else:
            row.name, row.coverage, row.mode = cam.name, cam.coverage, cam.mode
    for it in spec.items:
        row = db.scalar(select(D.InventoryItem).where(D.InventoryItem.centre_id == c.id, D.InventoryItem.item_key == it.id))
        vals = dict(class_name=it.class_name, description=it.description, cam_key=it.camera_id, bbox=it.bbox,
                    camera_verifiable=it.camera_verifiable)
        if row is None:
            db.add(D.InventoryItem(centre_id=c.id, item_key=it.id, **vals))
        else:
            for k, v in vals.items():
                setattr(row, k, v)
    return c


@app.put("/api/v1/registry/centres/{code}")
def register_centre(code: str, spec: S.CentreSpec, db: Session = Depends(get_db)) -> dict:
    if spec.code != code:
        raise HTTPException(400, "code mismatch")
    c = upsert_centre(db, spec)
    db.commit()
    return {"id": c.id, "code": c.code}


# ---------------------------------------------------------------- claims (mock MIS)
@app.post("/api/v1/claims")
async def import_claims(claims: list[S.ClaimIn], db: Session = Depends(get_db)) -> dict:
    touched = set()
    for cl in claims:
        c = centre_by_code(db, cl.centre_code)
        s = db.scalar(select(D.TrainingSession).where(D.TrainingSession.session_ref == cl.session_ref))
        if s is None:
            s = D.TrainingSession(centre_id=c.id, session_ref=cl.session_ref)
            db.add(s)
        s.batch, s.start, s.end = cl.batch, D.utc(cl.start), D.utc(cl.end)
        s.claimed_count, s.claim_source = cl.claimed_count, cl.source
        touched.add(c.id)
    db.flush()
    new = []
    for cid in touched:
        c = db.get(D.Centre, cid)
        new += [(a, c) for a in evaluate_centre(db, c)]
    db.commit()
    for a, c in new:
        await hub.broadcast({"type": "alert", "alert": alert_json(a, c)})
    return {"imported": len(claims)}


# ---------------------------------------------------------------- ingest
EVENT_ADAPTER = TypeAdapter(S.EventBatch)


@app.post("/api/v1/ingest/events")
async def ingest_events(request: Request, x_signature: str = Header(default=""), db: Session = Depends(get_db)) -> dict:
    raw = await request.body()
    wire_bytes = len(raw)
    if request.headers.get("content-encoding") == "gzip":
        raw = gzip.decompress(raw)
    expected = hmac.new(EDGE_SECRET, raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "bad signature")
    batch = EVENT_ADAPTER.validate_json(raw)
    c = centre_by_code(db, batch.centre_code)

    accepted = 0
    for ev in batch.events:
        ts = D.utc(ev.ts)
        cam = db.scalar(select(D.Camera).where(D.Camera.centre_id == c.id, D.Camera.cam_key == ev.camera_id))
        if cam is not None:
            cam.last_seen = max(cam.last_seen or ts, ts)
        if isinstance(ev, S.Heartbeat):
            dev = db.get(D.DeviceStat, c.id)
            if dev is None:
                dev = D.DeviceStat(centre_id=c.id, device_id=batch.device_id)
                db.add(dev)
            dev.device_id, dev.last_heartbeat, dev.queue_depth, dev.mode = batch.device_id, ts, ev.queue_depth, ev.mode
            dev.raw_video_bytes = max(dev.raw_video_bytes or 0, ev.raw_video_bytes)
            db.flush()
            continue
        model = {S.OccupancyWindow: D.OccupancyWindow, S.ItemCheck: D.ItemCheck, S.ItemUsage: D.ItemUsage, S.Tamper: D.TamperEvent}[type(ev)]
        if db.scalar(select(model.id).where(model.event_id == ev.event_id)) is not None:
            continue  # idempotent re-delivery
        if isinstance(ev, S.OccupancyWindow):
            db.add(D.OccupancyWindow(event_id=ev.event_id, centre_id=c.id, cam_key=ev.camera_id, session_ref=ev.session_ref,
                                     ts=ts, ts_end=D.utc(ev.ts_end), count_median=ev.count_median, count_p90=ev.count_p90,
                                     n_frames=ev.n_frames, thumb_id=ev.thumb_id))
            if db.scalar(select(D.TrainingSession).where(D.TrainingSession.session_ref == ev.session_ref)) is None:
                db.add(D.TrainingSession(centre_id=c.id, session_ref=ev.session_ref, start=ts, end=D.utc(ev.ts_end)))
                db.flush()
        elif isinstance(ev, S.ItemCheck):
            db.add(D.ItemCheck(event_id=ev.event_id, centre_id=c.id, item_key=ev.item_id, ts=ts, state=ev.state, sim=ev.sim,
                               det_conf=ev.det_conf, thumb_id=ev.thumb_id))
        elif isinstance(ev, S.ItemUsage):
            db.add(D.ItemUsage(event_id=ev.event_id, centre_id=c.id, item_key=ev.item_id, session_ref=ev.session_ref, ts=ts,
                               interaction_min=ev.interaction_min, observed_min=ev.observed_min))
        elif isinstance(ev, S.Tamper):
            db.add(D.TamperEvent(event_id=ev.event_id, centre_id=c.id, cam_key=ev.camera_id, kind=ev.kind, ts=ts,
                                 details=ev.details, thumb_id=ev.thumb_id))
        accepted += 1

    dev = db.get(D.DeviceStat, c.id)
    if dev is None:
        dev = D.DeviceStat(centre_id=c.id, device_id=batch.device_id)
        db.add(dev)
    dev.bytes_sent = (dev.bytes_sent or 0) + wire_bytes
    dev.events_received = (dev.events_received or 0) + len(batch.events)
    db.flush()
    new_alerts = evaluate_centre(db, c)
    db.commit()

    await hub.broadcast({"type": "ingest", "centre_code": c.code, "events": len(batch.events), "bytes": wire_bytes})
    for a in new_alerts:
        await hub.broadcast({"type": "alert", "alert": alert_json(a, c)})
    return {"accepted": accepted, "new_alerts": len(new_alerts)}


@app.post("/api/v1/ingest/thumbnails")
async def ingest_thumbnail(thumb_id: str = Form(...), centre_code: str = Form(...), file: UploadFile = File(...),
                           x_signature: str = Header(default=""), db: Session = Depends(get_db)) -> dict:
    if not THUMB_ID_RE.match(thumb_id):
        raise HTTPException(400, "bad thumb id")
    data = await file.read()
    expected = hmac.new(EDGE_SECRET, data, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_signature):
        raise HTTPException(401, "bad signature")
    (D.THUMB_DIR / f"{thumb_id}.jpg").write_bytes(data)
    c = db.scalar(select(D.Centre).where(D.Centre.code == centre_code))
    if c is not None:
        dev = db.get(D.DeviceStat, c.id)
        if dev is not None:
            dev.bytes_sent = (dev.bytes_sent or 0) + len(data)
            db.commit()
    return {"ok": True, "bytes": len(data)}


@app.get("/api/v1/thumbnails/{thumb_id}")
def get_thumbnail(thumb_id: str, actor: str = Query("demo-monitor"), db: Session = Depends(get_db)):
    if not THUMB_ID_RE.match(thumb_id):
        raise HTTPException(400, "bad thumb id")
    path = D.THUMB_DIR / f"{thumb_id}.jpg"
    if not path.exists():
        raise HTTPException(404)
    db.add(D.AuditLog(actor=actor, action="view_evidence", entity="thumbnail", entity_id=thumb_id))
    db.commit()
    return FileResponse(path, media_type="image/jpeg")


# ---------------------------------------------------------------- read API
def centre_summary(db: Session, c: D.Centre) -> dict:
    risk = risk_score(db, c)
    open_alerts = db.scalar(select(func.count(D.Alert.id)).where(D.Alert.centre_id == c.id,
                                                                 D.Alert.status.in_(("open", "ack", "assigned"))))
    dev = db.get(D.DeviceStat, c.id)
    return dict(id=c.id, code=c.code, name=c.name, state=c.state, district=c.district, lat=c.lat, lon=c.lon, scheme=c.scheme,
                trade=c.trade, sanctioned_seats=c.sanctioned_seats, simulated=c.simulated, risk=risk, open_alerts=open_alerts,
                device=dict(last_heartbeat=iso(dev.last_heartbeat), bytes_sent=dev.bytes_sent, raw_video_bytes=dev.raw_video_bytes,
                            queue_depth=dev.queue_depth, uptime_pct=dev.uptime_pct, mode=dev.mode) if dev else None)


@app.get("/api/v1/centres")
def list_centres(state: str | None = None, band: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    q = select(D.Centre)
    if state:
        q = q.where(D.Centre.state == state)
    out = [centre_summary(db, c) for c in db.scalars(q)]
    if band:
        out = [c for c in out if c["risk"]["band"] == band]
    return sorted(out, key=lambda c: -c["risk"]["score"])


@app.get("/api/v1/centres/{code}")
def get_centre(code: str, db: Session = Depends(get_db)) -> dict:
    c = centre_by_code(db, code)
    out = centre_summary(db, c)
    out["cameras"] = [dict(id=cam.cam_key, name=cam.name, coverage=cam.coverage, mode=cam.mode, last_seen=iso(cam.last_seen))
                      for cam in db.scalars(select(D.Camera).where(D.Camera.centre_id == c.id))]
    return out


@app.get("/api/v1/centres/{code}/attendance")
def get_attendance(code: str, db: Session = Depends(get_db)) -> list[dict]:
    c = centre_by_code(db, code)
    return [{**r, "start": iso(r["start"]), "end": iso(r["end"])} for r in session_attendance(db, c)]


@app.get("/api/v1/centres/{code}/occupancy")
def get_occupancy(code: str, session_ref: str | None = None, db: Session = Depends(get_db)) -> list[dict]:
    c = centre_by_code(db, code)
    q = select(D.OccupancyWindow).where(D.OccupancyWindow.centre_id == c.id).order_by(D.OccupancyWindow.ts)
    if session_ref:
        q = q.where(D.OccupancyWindow.session_ref == session_ref)
    return [dict(cam=w.cam_key, session_ref=w.session_ref, ts=iso(w.ts), ts_end=iso(w.ts_end), count_median=w.count_median,
                 count_p90=w.count_p90, n_frames=w.n_frames, thumb_id=w.thumb_id) for w in db.scalars(q)]


@app.get("/api/v1/centres/{code}/inventory")
def get_inventory(code: str, db: Session = Depends(get_db)) -> list[dict]:
    c = centre_by_code(db, code)
    out = []
    for it in db.scalars(select(D.InventoryItem).where(D.InventoryItem.centre_id == c.id)):
        checks = db.scalars(select(D.ItemCheck).where(D.ItemCheck.centre_id == c.id, D.ItemCheck.item_key == it.item_key)
                            .order_by(D.ItemCheck.ts.desc()).limit(10)).all()
        usage = db.scalars(select(D.ItemUsage).where(D.ItemUsage.centre_id == c.id, D.ItemUsage.item_key == it.item_key)
                           .order_by(D.ItemUsage.ts)).all()
        latest = checks[0] if checks else None
        out.append(dict(item_key=it.item_key, class_name=it.class_name, description=it.description, cam_key=it.cam_key,
                        camera_verifiable=it.camera_verifiable, state=latest.state if latest else "not_checked",
                        sim=latest.sim if latest else None, last_checked=iso(latest.ts) if latest else None,
                        thumb_id=latest.thumb_id if latest else None,
                        history=[dict(ts=iso(k.ts), state=k.state, sim=k.sim) for k in reversed(checks)],
                        usage=[dict(session_ref=u.session_ref, interaction_min=u.interaction_min) for u in usage]))
    return out


@app.get("/api/v1/alerts")
def list_alerts(status: str | None = None, severity: str | None = None, centre: str | None = None, kind: str | None = None,
                limit: int = 200, db: Session = Depends(get_db)) -> list[dict]:
    q = select(D.Alert, D.Centre).join(D.Centre, D.Centre.id == D.Alert.centre_id)
    if status:
        q = q.where(D.Alert.status.in_(status.split(",")))
    if severity:
        q = q.where(D.Alert.severity.in_(severity.split(",")))
    if centre:
        q = q.where(D.Centre.code == centre)
    if kind:
        q = q.where(D.Alert.kind.in_(kind.split(",")))
    rank = {"critical": 0, "warning": 1, "info": 2}
    rows = db.execute(q.order_by(D.Alert.opened_at.desc()).limit(limit)).all()
    return sorted((alert_json(a, c) for a, c in rows), key=lambda a: rank.get(a["severity"], 3))


class AlertPatch(BaseModel):
    status: str | None = None
    assignee: str | None = None
    resolution_note: str | None = None
    actor: str = "demo-monitor"


@app.patch("/api/v1/alerts/{alert_id}")
async def patch_alert(alert_id: int, body: AlertPatch, db: Session = Depends(get_db)) -> dict:
    a = db.get(D.Alert, alert_id)
    if not a:
        raise HTTPException(404)
    if body.status in ("resolved", "dismissed") and not (body.resolution_note or "").strip():
        raise HTTPException(400, "a note is required to resolve or dismiss")
    if body.status and body.status not in ("open", "ack", "assigned", "resolved", "dismissed"):
        raise HTTPException(400, "bad status")
    before = dict(status=a.status, assignee=a.assignee)
    for k in ("status", "assignee", "resolution_note"):
        v = getattr(body, k)
        if v is not None:
            setattr(a, k, v)
    a.updated_at = D.now()
    db.add(D.AuditLog(actor=body.actor, action="update_alert", entity="alert", entity_id=str(a.id),
                      diff=dict(before=before, after=dict(status=a.status, assignee=a.assignee))))
    db.commit()
    c = db.get(D.Centre, a.centre_id)
    out = alert_json(a, c)
    await hub.broadcast({"type": "alert_update", "alert": out})
    return out


@app.get("/api/v1/stats")
def stats(db: Session = Depends(get_db)) -> dict:
    centres = db.scalars(select(D.Centre)).all()
    summaries = [centre_summary(db, c) for c in centres]
    devs = db.scalars(select(D.DeviceStat)).all()
    open_by_sev = dict(db.execute(select(D.Alert.severity, func.count()).where(D.Alert.status.in_(("open", "ack", "assigned")))
                                  .group_by(D.Alert.severity)).all())
    return dict(
        centres=len(centres), real_centres=sum(not c.simulated for c in centres),
        bands={b: sum(s["risk"]["band"] == b for s in summaries) for b in ("low", "medium", "high")},
        open_alerts=open_by_sev, bytes_sent=sum(d.bytes_sent or 0 for d in devs),
        raw_video_bytes=sum(d.raw_video_bytes or 0 for d in devs),
        cameras=db.scalar(select(func.count(D.Camera.id))),
    )
