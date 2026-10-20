"""One-command demo.

    python scripts/demo.py              # API + dashboard on http://127.0.0.1:8000 (seeds the demo database if empty)
    python scripts/demo.py live [b|a|d] # run a centre's footage *live* through the edge AI with a blurred preview;
                                        # its claim is posted first, so the discrepancy alert pops up on the dashboard
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable
URL = os.environ.get("KNETRA_URL", "http://127.0.0.1:8000").rstrip("/")
IST = timezone(timedelta(hours=5, minutes=30))
LIVE_CLAIMS = {"b": 15, "a": 12, "d": 14}


def server_up() -> bool:
    try:
        return httpx.get(f"{URL}/api/v1/health", timeout=2).status_code == 200
    except httpx.HTTPError:
        return False


def start_server() -> subprocess.Popen | None:
    if server_up():
        print("server already running")
        return None
    if not (ROOT / "dashboard/dist/index.html").exists():
        print("building dashboard…")
        subprocess.run("npm run build", cwd=ROOT / "dashboard", shell=True, check=True)
    p = subprocess.Popen([PY, "-m", "uvicorn", "server.app.main:app", "--port", "8000"], cwd=ROOT)
    for _ in range(60):
        if server_up():
            break
        time.sleep(1)
    if not httpx.get(f"{URL}/api/v1/centres", timeout=30).json():
        subprocess.run([PY, "scripts/seed_demo.py"], cwd=ROOT, check=True)
    return p


def live(which: str) -> None:
    cfg = yaml.safe_load((ROOT / f"configs/centres/demo_{which}.yaml").read_text(encoding="utf-8"))
    now = datetime.now(IST).replace(microsecond=0)
    batch = f"LIVE-{now:%H%M}"
    cfg["device_id"] = f"edge-live-{which}-{now:%H%M%S}"
    cfg["server"] = {**cfg.get("server", {}), "url": URL, "secret": os.environ.get("KNETRA_EDGE_SECRET", "dev-secret")}
    if os.environ.get("KNETRA_DETECTOR"):  # e.g. yolo11n.onnx on a small host without PyTorch
        cfg["model"] = {**cfg.get("model", {}), "detector": os.environ["KNETRA_DETECTOR"]}
    (ROOT / "edge/var/OFFLINE").unlink(missing_ok=True)  # a previous run may have ended with the network "cut"
    cam = cfg["cameras"][0]
    for seg in cam["segments"]:
        seg["source"] = str((ROOT / "configs/centres" / seg["source"]).resolve())
    cam["segments"] = [dict(seg, start_time=now + timedelta(minutes=70 * i)) for i, seg in enumerate(cam["segments"][:1])]
    cfg["sessions"] = [{"batch": batch, "start": now, "end": now + timedelta(hours=1, minutes=5)}]
    ref = f"{cfg['centre']['code']}/{batch}/{now:%Y-%m-%d}"
    claim = [{"centre_code": cfg["centre"]["code"], "session_ref": ref, "batch": batch, "start": now.isoformat(),
              "end": (now + timedelta(hours=1, minutes=5)).isoformat(), "claimed_count": LIVE_CLAIMS.get(which, 15)}]
    print(httpx.post(f"{URL}/api/v1/claims", json=claim, timeout=30).json(), "claim posted for", ref)
    tmp = Path(tempfile.gettempdir()) / f"kn_live_{which}.yaml"
    tmp.write_text(yaml.safe_dump(cfg, sort_keys=False), encoding="utf-8")
    if "--no-browser" not in sys.argv:
        webbrowser.open(f"{URL}/live")
    subprocess.run([PY, "-m", "edge.agent", "--config", str(tmp), "--realtime", "--preview", "--speed", "0.5", "--drain-timeout", "30"],
                   cwd=ROOT, check=False)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "live":
        if not server_up():
            sys.exit("start the server first: python scripts/demo.py")
        args = [a for a in sys.argv[2:] if not a.startswith("--")]
        live(args[0] if args else "b")
    else:
        proc = start_server()
        if "--no-browser" not in sys.argv:
            webbrowser.open(URL)
        print(f"KaushalNetra running at {URL}  (Ctrl+C to stop)")
        if proc:
            try:
                proc.wait()
            except KeyboardInterrupt:
                proc.terminate()
