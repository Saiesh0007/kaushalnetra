"""Generate demo Centre C (IT lab, missing / covered / moved equipment) as a snapshot-mode camera.

Output: data/sim/centre_c/{ref_*.jpg, snaps/*.jpg, manifest.csv, ground_truth.json}
Timeline (IST) and what the system should conclude is recorded in ground_truth.json.
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.sim import scene as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/sim/centre_c"
BASE = cv2.imread(str(ROOT / "data/rooms/bYyytCaEAOY.jpg"))   # Unsplash, free licence
H, W = BASE.shape[:2]
ITEMS = [
    S.Item("PC-01", "computer monitor", (930, 636, 1030, 700)),    # added by hand at registration (YOLO-World missed it)
    S.Item("PC-02", "computer monitor", (1068, 635, 1179, 707)),
    S.Item("PC-03", "computer monitor", (1226, 637, 1343, 711)),
    S.Item("PC-04", "computer monitor", (1402, 636, 1532, 715)),
]
by_id = {i.id: i for i in ITEMS}

# (timestamp, events) — events apply cumulatively from that snapshot on, unless listed in `restore`
TIMELINE = [
    ("2026-10-13T08:30:00+05:30", {}),
    ("2026-10-13T18:30:00+05:30", {}),
    ("2026-10-14T08:30:00+05:30", {"remove": ["PC-02"], "cover": ["PC-04"]}),
    ("2026-10-14T13:00:00+05:30", {"occlude": ["PC-01"]}),
    ("2026-10-14T18:30:00+05:30", {"move": ["PC-03"]}),
    ("2026-10-15T08:30:00+05:30", {}),
    ("2026-10-15T18:30:00+05:30", {"dim": True}),
    ("2026-10-16T08:30:00+05:30", {"restore": ["PC-04"]}),
    ("2026-10-16T18:30:00+05:30", {"turn": True}),
]
MOVE_TO = {"PC-03": (1240, 755)}


def main() -> None:
    rng = np.random.default_rng(7)
    (OUT / "snaps").mkdir(parents=True, exist_ok=True)
    refs = []
    for k in range(3):   # registration views: same room, different exposure
        p = OUT / f"ref_{k}.jpg"
        cv2.imwrite(str(p), S.realism(BASE, rng, gamma=[1.0, 0.85, 1.15][k]))
        refs.append(p.name)

    removed, covered, moved = set(), set(), set()
    rows, truth = [], []
    for ts, ev in TIMELINE:
        removed |= set(ev.get("remove", []))
        covered |= set(ev.get("cover", []))
        moved |= set(ev.get("move", []))
        for r in ev.get("restore", []):
            covered.discard(r)
        img = BASE.copy()
        for i in sorted(removed):
            img = S.remove(img, by_id[i].box)
        for i in sorted(moved):
            img = S.move(img, by_id[i].box, MOVE_TO[i])
        for i in sorted(covered):
            img = S.cover(img, by_id[i].box, seed=sum(map(ord, i)))
        occluded = set(ev.get("occlude", []))
        for i in occluded:
            img, _ = S.occlude(img, by_id[i].box)
        img = S.realism(img, rng, gamma=1.9 if ev.get("dim") else None)
        if ev.get("turn"):
            img = S.turn_camera(img)
        name = f"snaps/{ts[:16].replace(':', '').replace('-', '')}.jpg"
        cv2.imwrite(str(OUT / name), img)
        rows.append({"ts": ts, "path": name})

        expect = {}
        for it in ITEMS:
            if ev.get("turn"):
                expect[it.id] = "camera_moved"
            elif it.id in occluded:
                expect[it.id] = "unverifiable"
            elif it.id in removed:
                expect[it.id] = "missing"
            elif it.id in moved:
                expect[it.id] = "relocated"
            elif it.id in covered:
                expect[it.id] = "changed"
            else:
                expect[it.id] = "present"
        truth.append({"ts": ts, "image": name, "expected": expect, "conditions": {k: v for k, v in ev.items()}})

    with open(OUT / "manifest.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["ts", "path"])
        wr.writeheader()
        wr.writerows(rows)
    (OUT / "ground_truth.json").write_text(json.dumps(dict(
        base_image="data/rooms/bYyytCaEAOY.jpg (Unsplash licence)", references=refs,
        items=[dict(id=i.id, class_name=i.class_name, bbox=i.norm(W, H)) for i in ITEMS], snapshots=truth), indent=1))
    print(f"wrote {len(rows)} snapshots + {len(refs)} references to {OUT}")


if __name__ == "__main__":
    main()
