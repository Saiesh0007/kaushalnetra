"""Rules engine: turns events into alerts, and computes the centre risk score (Design.md §2.3, §3.8, §4, §5, §6).

Every alert carries the evidence and thresholds that produced it (Rules.md §2.5).
"""
from __future__ import annotations

import math
import statistics
from collections import defaultdict
from datetime import timedelta
from pathlib import Path

import yaml
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import Alert, Camera, Centre, DeviceStat, InventoryItem, ItemCheck, ItemUsage, OccupancyWindow, TamperEvent, TrainingSession, now

CFG = yaml.safe_load((Path(__file__).resolve().parents[2] / "configs" / "rules.yaml").read_text())


# ---------------------------------------------------------------- attendance
def session_attendance(db: Session, centre: Centre) -> list[dict]:
    """Observed vs claimed for each session of a centre, oldest first."""
    cfg = CFG["attendance"]
    coverage = {c.cam_key: c.coverage or 1.0 for c in db.scalars(select(Camera).where(Camera.centre_id == centre.id))}
    sessions = db.scalars(
        select(TrainingSession).where(TrainingSession.centre_id == centre.id).order_by(TrainingSession.start)
    ).all()
    windows_by_session: dict[str, list[OccupancyWindow]] = defaultdict(list)
    for w in db.scalars(select(OccupancyWindow).where(OccupancyWindow.centre_id == centre.id)):
        windows_by_session[w.session_ref].append(w)

    out = []
    for s in sessions:
        wins = windows_by_session.get(s.session_ref, [])
        if not wins:
            out.append(dict(session_ref=s.session_ref, batch=s.batch, start=s.start, end=s.end, claimed=s.claimed_count,
                            observed=None, band=None, gap=None, gap_pct=None, flagged=False, n_windows=0))
            continue
        per_cam: dict[str, list[float]] = defaultdict(list)
        for w in wins:
            per_cam[w.cam_key].append(w.count_median)
        # Each training area is owned by exactly one camera (Design.md §1.3), so per-camera medians add up.
        observed = sum(statistics.median(v) / coverage.get(k, 1.0) for k, v in per_cam.items())
        observed = round(observed, 1)
        band = max(cfg["band_min"], math.ceil(cfg["band_pct"] * observed))
        claimed = s.claimed_count
        gap = gap_pct = None
        flagged = False
        if claimed is not None:
            gap = round(claimed - observed, 1)
            gap_pct = round(gap / max(claimed, 1), 3)
            flagged = gap > band and gap_pct > cfg["min_gap_pct"]
        out.append(dict(session_ref=s.session_ref, batch=s.batch, start=s.start, end=s.end, claimed=claimed,
                        observed=observed, band=band, gap=gap, gap_pct=gap_pct, flagged=flagged, n_windows=len(wins),
                        thumb_ids=[w.thumb_id for w in sorted(wins, key=lambda w: w.ts) if w.thumb_id][:6]))
    return out


def _attendance_alerts(db: Session, centre: Centre) -> None:
    cfg = CFG["attendance"]
    results = session_attendance(db, centre)
    observed_results = [r for r in results if r["observed"] is not None and r["claimed"] is not None]
    for i, r in enumerate(observed_results):
        recent = observed_results[max(0, i - cfg["persist_lookback"] + 1): i + 1]
        n_flagged = sum(x["flagged"] for x in recent)
        if r["flagged"]:
            persistent = n_flagged >= cfg["persist_sessions"]
            big = r["gap_pct"] >= cfg["single_session_warn_pct"]
            severity = "critical" if (persistent and big) else "warning" if (persistent or big) else "info"
            _upsert_alert(
                db, key=f"att:{r['session_ref']}", centre=centre, kind="attendance", severity=severity,
                title=f"Attendance discrepancy: claimed {r['claimed']}, observed {r['observed']:g} ± {r['band']}",
                detail=(f"Session {r['session_ref']}: gap {r['gap']:g} ({r['gap_pct']:.0%} of claimed). "
                        f"{n_flagged} of the last {len(recent)} observed sessions were flagged."),
                evidence=dict(session_ref=r["session_ref"], claimed=r["claimed"], observed=r["observed"], band=r["band"],
                              gap_pct=r["gap_pct"], flagged_recent=n_flagged, thumb_ids=r.get("thumb_ids", []),
                              thresholds=cfg),
                ts=r["start"],
            )
        seats = centre.sanctioned_seats
        if r["observed"] > seats + r["band"]:
            _upsert_alert(
                db, key=f"occ:{r['session_ref']}", centre=centre, kind="over_occupancy", severity="warning",
                title=f"Over-occupancy: observed {r['observed']:g} vs {seats} sanctioned seats",
                detail="More trainees observed than sanctioned seats; possible unsanctioned batch.",
                evidence=dict(session_ref=r["session_ref"], observed=r["observed"], seats=seats, thumb_ids=r.get("thumb_ids", [])),
                ts=r["start"],
            )


# ---------------------------------------------------------------- infrastructure
def _item_alerts(db: Session, centre: Centre) -> None:
    cfg = CFG["items"]
    for item in db.scalars(select(InventoryItem).where(InventoryItem.centre_id == centre.id)):
        checks = db.scalars(
            select(ItemCheck).where(ItemCheck.centre_id == centre.id, ItemCheck.item_key == item.item_key)
            .order_by(ItemCheck.ts.desc())
        ).all()
        if not checks:
            continue
        latest = checks[0]
        for state, kind, sev, label in (("candidate_missing", "item_missing", "warning", "not found at its registered position"),
                                        ("changed", "item_changed", "info", "appearance changed (covered or swapped?)")):
            run = []
            for c in checks:  # newest first; skip unverifiable checks rather than breaking the run
                if c.state == state:
                    run.append(c)
                elif c.state in ("unverifiable", "uncertain"):
                    continue
                else:
                    break
            key = f"{kind}:{centre.code}:{item.item_key}"
            if run and len(run) >= cfg["persist_checks"]:
                days = len({c.ts.date() for c in run})
                if days >= cfg["min_days"]:
                    _upsert_alert(
                        db, key=key, centre=centre, kind=kind, severity=sev,
                        title=f"{item.class_name.title()} {item.item_key} {label}",
                        detail=f"{len(run)} consecutive checks over {days} days. Last similarity {run[0].sim}.",
                        evidence=dict(item_key=item.item_key, checks=[dict(ts=c.ts.isoformat(), state=c.state, sim=c.sim,
                                      det_conf=c.det_conf, thumb_id=c.thumb_id) for c in run[:6]],
                                      thumb_ids=[c.thumb_id for c in run if c.thumb_id][:6], thresholds=cfg),
                        ts=run[-1].ts,
                    )
            elif latest.state in ("present", "relocated"):
                _auto_resolve(db, key, f"auto: item observed {latest.state} at {latest.ts:%Y-%m-%d %H:%M} UTC")

    # usage evidence (Design.md §4)
    ucfg = CFG["usage"]
    att = {r["session_ref"]: r for r in session_attendance(db, centre)}
    usage_by_item: dict[str, list[ItemUsage]] = defaultdict(list)
    for u in db.scalars(select(ItemUsage).where(ItemUsage.centre_id == centre.id).order_by(ItemUsage.ts)):
        usage_by_item[u.item_key].append(u)
    for item_key, rows in usage_by_item.items():
        qualifying = []
        for u in rows:
            a = att.get(u.session_ref)
            if a and a["observed"] and a["claimed"] and a["observed"] >= ucfg["min_attendance_ratio"] * a["claimed"]:
                qualifying.append(u)
        recent = qualifying[-ucfg["min_sessions"]:]
        key = f"unused:{centre.code}:{item_key}"
        if len(recent) >= ucfg["min_sessions"] and all(u.interaction_min == 0 for u in recent):
            _upsert_alert(db, key=key, centre=centre, kind="item_unused", severity="warning",
                          title=f"No observed use of {item_key} in {len(recent)} sessions",
                          detail="No observed use while trainees were present; verify operability on inspection.",
                          evidence=dict(item_key=item_key, sessions=[u.session_ref for u in recent]), ts=recent[-1].ts)
        elif recent and recent[-1].interaction_min > 0:
            _auto_resolve(db, key, "auto: use observed")


# ---------------------------------------------------------------- tamper
TAMPER_TITLES = {
    "frozen": "Camera feed frozen", "looped": "Camera feed appears looped (replayed footage)",
    "covered": "Camera covered or blacked out", "camera_moved": "Camera moved from registered position",
    "camera_offline": "Camera offline during session",
}


def _tamper_alerts(db: Session, centre: Centre) -> None:
    dedupe = timedelta(minutes=CFG["tamper"]["dedupe_minutes"])
    last: dict[tuple[str, str], object] = {}
    for t in db.scalars(select(TamperEvent).where(TamperEvent.centre_id == centre.id).order_by(TamperEvent.ts)):
        k = (t.cam_key, t.kind)
        prev = last.get(k)
        if prev is not None and t.ts - prev.ts < dedupe:
            continue
        last[k] = t
        _upsert_alert(db, key=f"tamper:{centre.code}:{t.cam_key}:{t.kind}:{t.ts:%Y%m%d%H%M}", centre=centre, kind="tamper",
                      severity="critical", title=f"{TAMPER_TITLES.get(t.kind, t.kind)} ({t.cam_key})",
                      detail=", ".join(f"{k}={v}" for k, v in (t.details or {}).items()),
                      evidence=dict(cam_key=t.cam_key, kind=t.kind, details=t.details,
                                    thumb_ids=[t.thumb_id] if t.thumb_id else []), ts=t.ts)


# ---------------------------------------------------------------- alert helpers
_new_alerts: list[Alert] = []


def _upsert_alert(db: Session, *, key, centre, kind, severity, title, detail, evidence, ts) -> None:
    a = db.scalar(select(Alert).where(Alert.key == key))
    if a is None:
        a = Alert(key=key, centre_id=centre.id, kind=kind, severity=severity, status="open", title=title, detail=detail,
                  evidence=evidence, opened_at=ts or now(), updated_at=now())
        db.add(a)
        _new_alerts.append(a)
    else:
        a.severity, a.title, a.detail, a.evidence, a.updated_at = severity, title, detail, evidence, now()


def _auto_resolve(db: Session, key: str, note: str) -> None:
    a = db.scalar(select(Alert).where(Alert.key == key))
    if a and a.status in ("open", "ack", "assigned"):
        a.status, a.resolution_note, a.updated_at = "resolved", note, now()


def evaluate_centre(db: Session, centre: Centre) -> list[Alert]:
    """Re-run all rules for one centre. Idempotent. Returns alerts created in this run."""
    _new_alerts.clear()
    _attendance_alerts(db, centre)
    _item_alerts(db, centre)
    _tamper_alerts(db, centre)
    db.flush()
    return list(_new_alerts)


# ---------------------------------------------------------------- risk score
def risk_score(db: Session, centre: Centre) -> dict:
    cfg = CFG["risk"]
    since = now() - timedelta(days=cfg["window_days"])
    att = [r for r in session_attendance(db, centre) if r["gap_pct"] is not None]
    recent_att = [r for r in att if r["start"] >= since] or att[-5:]
    attendance = min(1.0, statistics.mean(max(0.0, r["gap_pct"]) for r in recent_att)) if recent_att else 0.0

    verifiable = db.scalars(select(InventoryItem).where(InventoryItem.centre_id == centre.id,
                                                        InventoryItem.camera_verifiable.is_(True))).all()
    open_alerts = db.scalars(select(Alert).where(Alert.centre_id == centre.id, Alert.status.in_(("open", "ack", "assigned")))).all()
    n_items = max(len(verifiable), 1)
    infra = min(1.0, sum(a.kind in ("item_missing", "item_changed") for a in open_alerts) / n_items) if verifiable else 0.0
    usage = min(1.0, sum(a.kind == "item_unused" for a in open_alerts) / n_items) if verifiable else 0.0
    tamper = min(1.0, sum(a.kind == "tamper" for a in open_alerts) / 3)
    dev = db.get(DeviceStat, centre.id)
    uptime = 1.0 - (dev.uptime_pct if dev else 1.0)

    comps = dict(attendance=attendance, infra=infra, usage=usage, tamper=tamper, uptime=uptime)
    score = round(sum(cfg["weights"][k] * v for k, v in comps.items()), 1)
    band = "high" if score >= cfg["bands"]["high"] else "medium" if score >= cfg["bands"]["medium"] else "low"
    return dict(score=score, band=band, components={k: round(v, 3) for k, v in comps.items()}, weights=cfg["weights"])
