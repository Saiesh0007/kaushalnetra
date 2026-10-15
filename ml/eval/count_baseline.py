"""Count accuracy on SCUT-HEAD PartA test split: predicted count vs annotated heads per image."""
import argparse, json, statistics, time, xml.etree.ElementTree as ET
from pathlib import Path
from ultralytics import YOLO

ap = argparse.ArgumentParser()
ap.add_argument("--weights", default="yolo11n.pt")
ap.add_argument("--classes", type=int, nargs="*", default=[0])
ap.add_argument("--conf", type=float, default=0.3)
ap.add_argument("--imgsz", type=int, default=640)
ap.add_argument("--n", type=int, default=100)
ap.add_argument("--out")
a = ap.parse_args()
root = Path("data/scut/SCUT_HEAD_Part_A")
ids = (root / "ImageSets/Main/test.txt").read_text().split()[: a.n]
m = YOLO(a.weights)
errs, rows, t = [], [], time.time()
for i in ids:
    gt = len(ET.parse(root / f"Annotations/{i}.xml").findall("object"))
    r = m.predict(str(root / f"JPEGImages/{i}.jpg"), conf=a.conf, imgsz=a.imgsz, classes=a.classes or None, verbose=False)[0]
    pred = len(r.boxes)
    errs.append(pred - gt); rows.append((i, gt, pred))
abs_e = [abs(e) for e in errs]
gts = [g for _, g, _ in rows]
res = dict(weights=a.weights, n=len(ids), conf=a.conf, imgsz=a.imgsz, mean_gt=round(statistics.mean(gts), 1),
           mae=round(statistics.mean(abs_e), 2), bias=round(statistics.mean(errs), 2),
           within_10pct=round(sum(abs(p - g) <= 0.1 * g for _, g, p in rows) / len(rows), 3),
           sec_per_img=round((time.time() - t) / len(ids), 3))
print(json.dumps(res))
if a.out:
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(dict(summary=res, rows=rows), indent=1))
