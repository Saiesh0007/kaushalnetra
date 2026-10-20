"""Assemble the hosted-demo Docker build folder: only what the hosted demo needs, never .env.

    python scripts/build_web.py [--db DIR]    # DIR = a freshly seeded server var dir (default server/var)

Writes deploy/web/build/. Build the dashboard first (cd dashboard && npm run build). Then:
    docker build -t <user>/kaushalnetra deploy/web/build
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path

import cv2
import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "deploy/web/build"
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

    # live runs use the first clip of each live centre and the person detector exported to ONNX (no PyTorch needed)
    for which in ("a", "b"):
        cfg = yaml.safe_load((ROOT / f"configs/centres/demo_{which}.yaml").read_text(encoding="utf-8"))
        src = (ROOT / "configs/centres" / cfg["cameras"][0]["segments"][0]["source"]).resolve()
        dst = OUT / src.relative_to(ROOT)
        dst.parent.mkdir(parents=True, exist_ok=True)
        # The agent analyses one frame every `step` but must decode them all, which dominates on a small hosted CPU.
        # Keep exactly the analysed frames as a 1 fps clip: same frames, same sample times, a fraction of the decoding.
        cap = cv2.VideoCapture(str(src))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        cap.release()
        step = max(1, round(fps * cfg["sampling"]["interval_s"] / cfg["cameras"][0]["time_scale"]))
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vf", f"select=not(mod(n\\,{step})),setpts=N/TB",
                        "-r", "1", "-an", "-c:v", "libx264", "-crf", "18", "-g", "1", str(dst)], check=True)
    if not (ROOT / "yolo11n.onnx").exists():
        raise SystemExit("export the detector first: yolo export model=yolo11n.pt format=onnx imgsz=640 simplify=True")
    shutil.copy2(ROOT / "yolo11n.onnx", OUT / "yolo11n.onnx")

    for f in ("Dockerfile", "requirements.txt"):
        shutil.copy2(ROOT / "deploy/web" / f, OUT / f)
    assert not list(OUT.rglob(".env")), ".env must never be published"
    size = sum(f.stat().st_size for f in OUT.rglob("*") if f.is_file())
    print(f"{OUT}  ({size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
