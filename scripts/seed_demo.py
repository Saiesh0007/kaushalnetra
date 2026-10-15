"""Populate a fresh server with the full demo: real-footage centres A-D, mock MIS claims, simulated fleet.

    python scripts/seed_demo.py [--url http://127.0.0.1:8000] [--skip-fleet]
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

ap = argparse.ArgumentParser()
ap.add_argument("--url", default="http://127.0.0.1:8000")
ap.add_argument("--skip-fleet", action="store_true")
a = ap.parse_args()


def run(*args):
    print(">", " ".join(args), flush=True)
    subprocess.run([PY, *args], cwd=ROOT, check=True)


if not (ROOT / "data/sim/centre_c/manifest.csv").exists():
    run("scripts/make_centre_c.py")
for c in ("demo_a", "demo_b", "demo_c", "demo_d"):
    run("-m", "edge.agent", "--config", f"configs/centres/{c}.yaml")
run("scripts/push_claims.py", a.url)
if not a.skip_fleet:
    run("scripts/sim_fleet.py", "--url", a.url)
print("demo seeded")
