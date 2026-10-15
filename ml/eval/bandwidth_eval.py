"""Measured upload volume of the AI-pipeline demo centres vs the video they replaced (from the server's device stats).

    python ml/eval/bandwidth_eval.py [--url http://127.0.0.1:8000]
"""
import argparse
import json
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8000")
a = ap.parse_args()

rows = []
for c in httpx.get(f"{a.url}/api/v1/centres", timeout=60).json():
    if c["simulated"] or not c["device"]:
        continue
    d = c["device"]
    att = httpx.get(f"{a.url}/api/v1/centres/{c['code']}/attendance", timeout=60).json()
    hours = sum((__import__("datetime").datetime.fromisoformat(s["end"][:-1]) - __import__("datetime").datetime.fromisoformat(s["start"][:-1])).total_seconds()
                for s in att if s["n_windows"]) / 3600
    rows.append(dict(centre=c["code"], mode=d["mode"], bytes_sent=d["bytes_sent"], raw_video_bytes=d["raw_video_bytes"],
                     reduction=round(d["raw_video_bytes"] / d["bytes_sent"]) if d["raw_video_bytes"] else None,
                     session_hours=round(hours, 2),
                     kb_per_session_hour=round(d["bytes_sent"] / 1024 / hours, 1) if hours else None))
sent = sum(r["bytes_sent"] for r in rows if r["raw_video_bytes"])
raw = sum(r["raw_video_bytes"] for r in rows)
hours = sum(r["session_hours"] for r in rows if r["raw_video_bytes"])
out = dict(centres=rows, total_sent=sent, total_raw=raw, overall_reduction=round(raw / sent) if sent else None,
           kb_per_camera_hour=round(sent / 1024 / hours, 1) if hours else None,
           mb_per_camera_day_8h=round(sent / 1024 / 1024 / hours * 8, 2) if hours else None,
           note="Raw video = what streaming the same centre time at 1 Mbps (720p H.264) would upload. Includes all evidence thumbnails.")
(ROOT / "ml/results").mkdir(parents=True, exist_ok=True)
(ROOT / "ml/results/bandwidth.json").write_text(json.dumps(out, indent=1))
print(json.dumps({k: v for k, v in out.items() if k != "centres"}, indent=1))
