"""Fleet simulator: synthetic centres across India, sent through the real ingest API as if from edge devices.

Every simulated centre is flagged `simulated=True` and carries no imagery. They exist so the national view
looks like a deployment; all accuracy claims come from real footage and labelled datasets, never from here.

    python scripts/sim_fleet.py [--n 60] [--days 14] [--url http://127.0.0.1:8000]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import hmac
import random
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import schemas as S  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
SECRET = b"dev-secret"

CITIES = [  # (district, state, lat, lon)
    ("Indore", "Madhya Pradesh", 22.72, 75.86), ("Bhopal", "Madhya Pradesh", 23.26, 77.41),
    ("Jaipur", "Rajasthan", 26.91, 75.79), ("Jodhpur", "Rajasthan", 26.24, 73.02),
    ("Ahmedabad", "Gujarat", 23.02, 72.57), ("Surat", "Gujarat", 21.17, 72.83),
    ("Nashik", "Maharashtra", 20.00, 73.79), ("Aurangabad", "Maharashtra", 19.88, 75.34),
    ("Kolhapur", "Maharashtra", 16.70, 74.24), ("Varanasi", "Uttar Pradesh", 25.32, 82.97),
    ("Kanpur", "Uttar Pradesh", 26.45, 80.33), ("Gorakhpur", "Uttar Pradesh", 26.76, 83.37),
    ("Gaya", "Bihar", 24.79, 85.00), ("Muzaffarpur", "Bihar", 26.12, 85.39),
    ("Ranchi", "Jharkhand", 23.34, 85.31), ("Bhubaneswar", "Odisha", 20.30, 85.82),
    ("Kolkata", "West Bengal", 22.57, 88.36), ("Siliguri", "West Bengal", 26.73, 88.40),
    ("Guwahati", "Assam", 26.14, 91.74), ("Hyderabad", "Telangana", 17.39, 78.49),
    ("Warangal", "Telangana", 17.97, 79.59), ("Vijayawada", "Andhra Pradesh", 16.51, 80.65),
    ("Bengaluru", "Karnataka", 12.97, 77.59), ("Hubballi", "Karnataka", 15.36, 75.12),
    ("Chennai", "Tamil Nadu", 13.08, 80.27), ("Madurai", "Tamil Nadu", 9.93, 78.12),
    ("Kochi", "Kerala", 9.93, 76.27), ("Raipur", "Chhattisgarh", 21.25, 81.63),
    ("Dehradun", "Uttarakhand", 30.32, 78.03), ("Ludhiana", "Punjab", 30.90, 75.86),
]
TRADES = {
    "IT-ITeS": [("computer monitor", 10)], "Apparel": [("sewing machine", 12)],
    "Electronics": [("workbench", 6), ("computer monitor", 4)], "Automotive": [("workbench", 4)],
    "Beauty & Wellness": [("salon chair", 6)], "Retail": [("computer monitor", 4)],
}
PROFILES = [("honest", 0.68), ("inflated", 0.14), ("equipment", 0.08), ("tamper", 0.05), ("offline", 0.05)]


def sign(raw: bytes) -> str:
    return hmac.new(SECRET, raw, hashlib.sha256).hexdigest()


def eid(*parts) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join(map(str, parts))))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=60)
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--url", default="http://127.0.0.1:8000")
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    client = httpx.Client(timeout=60)
    today = datetime.now(IST).replace(hour=0, minute=0, second=0, microsecond=0)
    profiles = [p for p, _ in PROFILES]
    weights = [w for _, w in PROFILES]
    summary: dict[str, int] = {}

    for n in range(a.n):
        district, state, lat, lon = CITIES[n % len(CITIES)]
        code = f"KN-SIM-{n + 1:03d}"
        trade = rng.choice(list(TRADES))
        profile = rng.choices(profiles, weights)[0]
        summary[profile] = summary.get(profile, 0) + 1
        seats = rng.choice([20, 25, 30, 30, 40])
        items = []
        for cls, k in TRADES[trade]:
            for j in range(k):
                items.append(S.ItemSpec(id=f"{cls[:3].upper()}-{j + 1:02d}", class_name=cls, camera_id="cam-1",
                                        bbox=[0.1, 0.1, 0.2, 0.2], camera_verifiable=rng.random() > 0.1))
        spec = S.CentreSpec(code=code, name=f"Simulated Centre {n + 1:03d}", state=state, district=district,
                            lat=lat + rng.uniform(-0.15, 0.15), lon=lon + rng.uniform(-0.15, 0.15), trade=trade,
                            sanctioned_seats=seats, simulated=True, items=items,
                            cameras=[S.CameraSpec(id="cam-1", name="Training room", coverage=round(rng.uniform(0.8, 1.0), 2))])
        client.put(f"{a.url}/api/v1/registry/centres/{code}", json=spec.model_dump(mode="json")).raise_for_status()

        events, claims = [], []
        batch_size = int(seats * rng.uniform(0.7, 1.0))
        severe = rng.random() < 0.45
        offline_rate = rng.uniform(0.1, 0.35)
        inflate_range = (0.35, 0.6) if severe else (0.65, 0.82)   # mild inflation is far more common than blatant
        inflate_days = rng.randint(5, 12)
        bad_items = rng.sample([i.id for i in items if i.camera_verifiable], k=rng.choice([1, 1, 2])) if profile == "equipment" else []
        for d in range(a.days, 0, -1):
            day = today - timedelta(days=d)
            if day.weekday() == 6:
                continue  # Sundays off
            for slot, hour in (("AM", 9), ("PM", 14)):
                start = day.replace(hour=hour)
                end = start + timedelta(hours=3)
                sref = f"{code}/B{slot}/{start:%Y-%m-%d}"
                present = batch_size * rng.uniform(0.82, 1.0)
                claimed = round(present + rng.choice([0, 0, 0, 1]))
                if profile == "inflated" and d <= inflate_days:
                    present = batch_size * rng.uniform(*inflate_range)
                    claimed = batch_size
                offline = profile == "offline" and rng.random() < offline_rate
                claims.append(dict(centre_code=code, session_ref=sref, batch=f"B{slot}", start=start.isoformat(),
                                   end=end.isoformat(), claimed_count=claimed, source="mis-mock"))
                if offline:
                    continue
                for w in range(12):
                    ws = start + timedelta(minutes=15 * w)
                    c = max(0, round(present * spec.cameras[0].coverage + rng.gauss(0, 0.8)))
                    events.append(S.OccupancyWindow(event_id=eid(code, "occ", ws), camera_id="cam-1", ts=ws,
                                                    ts_end=ws + timedelta(minutes=15), session_ref=sref,
                                                    count_median=c, count_p90=c + rng.choice([0, 1, 1, 2]), n_frames=30))
            for hour in (8, 18):
                ts = day.replace(hour=hour, minute=30)
                for it in items:
                    if not it.camera_verifiable:
                        continue
                    state = "present"
                    if it.id in bad_items and d <= 4:
                        state = rng.choice(["candidate_missing", "candidate_missing", "changed"])
                    elif rng.random() < 0.03:
                        state = "unverifiable"
                    sim = round(rng.uniform(0.85, 0.97), 3) if state == "present" else (round(rng.uniform(0.25, 0.5), 3) if state != "unverifiable" else None)
                    events.append(S.ItemCheck(event_id=eid(code, it.id, ts), camera_id="cam-1", ts=ts, item_id=it.id,
                                              state=state, sim=sim, det_conf=0.0))
        if profile == "tamper":
            ts = today - timedelta(days=rng.randint(1, 3)) + timedelta(hours=rng.choice([10, 11, 15]))
            kind = rng.choice(["looped", "covered", "frozen", "camera_moved"])
            events.append(S.Tamper(event_id=eid(code, "tamper", ts), camera_id="cam-1", ts=ts, kind=kind,
                                   details={"simulated": True}))
        uptime = 1 - offline_rate if profile == "offline" else rng.uniform(0.96, 1.0)
        raw = int(a.days * 6 * 3600 * 1_000_000 / 8)   # what 6 h/day of 1 Mbps streaming would have cost
        events.append(S.Heartbeat(camera_id="cam-1", ts=datetime.now(IST), raw_video_bytes=raw, uptime_pct=round(uptime, 3)))

        client.post(f"{a.url}/api/v1/claims", json=claims).raise_for_status()
        for i in range(0, len(events), 500):
            batch = S.EventBatch(device_id=f"sim-{code}", centre_code=code, sent_at=datetime.now(IST), events=events[i:i + 500])
            raw_json = batch.model_dump_json().encode()
            client.post(f"{a.url}/api/v1/ingest/events", content=gzip.compress(raw_json),
                        headers={"content-type": "application/json", "content-encoding": "gzip",
                                 "x-signature": sign(raw_json)}).raise_for_status()
        print(f"{code} {district:12s} {trade:18s} {profile:9s} events={len(events)}")
    print("profiles:", summary)


if __name__ == "__main__":
    main()
