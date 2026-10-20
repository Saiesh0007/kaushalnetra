"""Assemble the Hugging Face Space folder: only what the hosted demo needs, never .env.

    python scripts/build_space.py [--db DIR]    # DIR = a freshly seeded server var dir (default server/var)

Writes deploy/space/build/. Build the dashboard first (cd dashboard && npm run build).
"""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy/space/build"
SKIP = shutil.ignore_patterns("__pycache__", "*.pyc", "var", ".env")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(ROOT / "server/var"), help="seeded var dir (kaushalnetra.db + thumbs/)")
    db = Path(ap.parse_args().db)
    if not (db / "kaushalnetra.db").exists():
        raise SystemExit(f"no kaushalnetra.db in {db}")
    if not (ROOT / "dashboard/dist/index.html").exists():
        raise SystemExit("build the dashboard first: cd dashboard && npm run build")

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    for d in ("common", "server", "edge", "configs", "ml/results", "dashboard/dist"):
        shutil.copytree(ROOT / d, OUT / d, ignore=SKIP)
    (OUT / "scripts").mkdir()
    shutil.copy2(ROOT / "scripts/demo.py", OUT / "scripts/demo.py")
    (OUT / "edge/var").mkdir()
    shutil.copytree(db, OUT / "server/var", ignore=shutil.ignore_patterns("live_demo.log", "*-journal"))

    # live runs use the first clip of each live centre and the stock person detector
    for which in ("a", "b"):
        cfg = yaml.safe_load((ROOT / f"configs/centres/demo_{which}.yaml").read_text(encoding="utf-8"))
        src = (ROOT / "configs/centres" / cfg["cameras"][0]["segments"][0]["source"]).resolve()
        dst = OUT / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    detector = yaml.safe_load((ROOT / "configs/centres/demo_b.yaml").read_text(encoding="utf-8")).get("model", {}).get("detector", "yolo11n.pt")
    shutil.copy2(ROOT / detector, OUT / detector)

    for f in ("Dockerfile", "requirements.txt", "README.md"):
        shutil.copy2(ROOT / "deploy/space" / f, OUT / f)
    assert not list(OUT.rglob(".env")), ".env must never be published"
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"{OUT}  ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
