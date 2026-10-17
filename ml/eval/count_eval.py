"""Head-count accuracy on the held-out SCUT-HEAD PartA test split (real classroom CCTV, labelled heads),
plus a degradation study: accuracy vs resolution / JPEG quality / darkness / noise, with the bytes each frame costs.

Test images were never used for training or threshold tuning (Rules.md §2.2).

    python ml/eval/count_eval.py --head runs/detect/ml/runs/head_yolo11n/weights/best.pt [--n 500] [--n-deg 150]
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[2]
SCUT = ROOT / "data/scut/SCUT_HEAD_Part_A"


def load_test(n: int) -> list[tuple[np.ndarray, int]]:
    ids = (SCUT / "ImageSets/Main/test.txt").read_text().split()[:n]
    return [(cv2.imread(str(SCUT / f"JPEGImages/{i}.jpg")), len(ET.parse(SCUT / f"Annotations/{i}.xml").findall("object"))) for i in ids]


def metrics(pairs: list[tuple[int, int]]) -> dict:
    err = [p - g for g, p in pairs]
    return dict(n=len(pairs), mean_gt=round(statistics.mean(g for g, _ in pairs), 1), mae=round(statistics.mean(abs(e) for e in err), 2),
                rmse=round(float(np.sqrt(np.mean(np.square(err)))), 2), bias=round(statistics.mean(err), 2),
                within_10pct=round(sum(abs(p - g) <= 0.1 * g for g, p in pairs) / len(pairs), 3),
                mape=round(statistics.mean(abs(p - g) / max(g, 1) for g, p in pairs), 3))


def count(model: YOLO, img: np.ndarray, classes, conf: float, imgsz: int) -> int:
    return len(model.predict(img, conf=conf, imgsz=imgsz, classes=classes, verbose=False)[0].boxes)


def degrade(img: np.ndarray, kind: str, v: float) -> tuple[np.ndarray, int]:
    """Returns the degraded frame and its upload size as a JPEG (what Snapshot mode would send)."""
    q = 75
    if kind == "resolution":
        h, w = img.shape[:2]
        img = cv2.resize(img, (int(w * v), int(h * v)), interpolation=cv2.INTER_AREA)
    elif kind == "jpeg_quality":
        q = int(v)
    elif kind == "darkness_gamma":
        img = np.clip(((img / 255.0) ** v) * 255, 0, 255).astype(np.uint8)
    elif kind == "noise_sigma":
        img = np.clip(img + np.random.default_rng(0).normal(0, v, img.shape), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, q])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR), len(buf)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--head", required=True)
    ap.add_argument("--n", type=int, default=500)
    ap.add_argument("--n-deg", type=int, default=150)
    ap.add_argument("--conf", type=float, default=None, help="fixed confidence; default: select on the VAL split")
    a = ap.parse_args()
    t0 = time.time()
    data = load_test(a.n)
    base, head = YOLO(str(ROOT / "yolo11n.pt")), YOLO(str(ROOT / a.head))

    # choose the confidence threshold on the validation split only (Rules.md §2.2); test stays untouched
    val_ids = (SCUT / "ImageSets/Main/val.txt").read_text().split()[:150]
    val = [(cv2.imread(str(SCUT / f"JPEGImages/{i}.jpg")), len(ET.parse(SCUT / f"Annotations/{i}.xml").findall("object"))) for i in val_ids]
    conf_scan = {}
    if a.conf is None:
        for c in (0.2, 0.25, 0.3, 0.35, 0.4, 0.45, 0.5):
            conf_scan[c] = metrics([(g, count(head, img, None, c, 640)) for img, g in val])["mae"]
        a.conf = min(conf_scan, key=conf_scan.get)
        print("val conf scan (MAE):", conf_scan, "-> conf", a.conf, flush=True)

    models = []
    for name, m, cls, c in (("YOLO11n person (off-the-shelf)", base, [0], 0.25),
                            ("KaushalNetra head detector (fine-tuned YOLO11n)", head, None, a.conf)):
        pairs = [(g, count(m, img, cls, c, 640)) for img, g in data]
        models.append(dict(name=name, **metrics(pairs)))
        print(models[-1], flush=True)

    deg = []
    sub = data[: a.n_deg]
    for kind, values in (("resolution", [1.0, 0.75, 0.5, 0.35]), ("jpeg_quality", [90, 50, 25, 10]),
                         ("darkness_gamma", [1.0, 1.6, 2.2, 2.8]), ("noise_sigma", [0, 10, 20, 30])):
        for v in values:
            pairs, sizes = [], []
            for img, g in sub:
                d, nbytes = degrade(img, kind, v)
                sizes.append(nbytes)
                pairs.append((g, count(head, d, None, a.conf, 640)))
            deg.append(dict(condition=kind, value=v, kb_per_frame=round(statistics.mean(sizes) / 1024, 1), **metrics(pairs)))
            print(deg[-1], flush=True)

    out = dict(dataset=f"SCUT-HEAD PartA test split (held out), first {a.n} images; degradation on first {a.n_deg}",
               licence_note="SCUT-HEAD: free for academic research use", conf=a.conf, conf_selected_on_val=conf_scan, imgsz=640, models=models,
               degradation=deg, seconds=round(time.time() - t0))
    (ROOT / "ml/results").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml/results/count_eval.json").write_text(json.dumps(out, indent=1))
    print("done", round(time.time() - t0), "s")


if __name__ == "__main__":
    main()
