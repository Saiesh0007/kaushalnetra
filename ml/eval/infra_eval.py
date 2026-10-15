"""Equipment-check accuracy on randomised simulated scenarios with exact ground truth (Design.md §9.2).

For each room photo: register items from 3 reference views, then generate N snapshots in which every item is
independently present / removed / covered / occluded by a person, with random dim lighting and occasional camera turns.
Reports per-check confusion, anomaly precision/recall, false-alarm rate on present items, and camera-moved detection.

    python ml/eval/infra_eval.py [--n 40] [--seed 1]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from edge.agent.config import InfraCfg  # noqa: E402
from edge.agent.infra import Embedder, ItemVerifier, OpenVocabDetector  # noqa: E402
from ml.sim import scene as S  # noqa: E402

ROOMS = {
    "it_lab": ("data/rooms/bYyytCaEAOY.jpg", [
        S.Item("PC-01", "computer monitor", (930, 636, 1030, 700)),
        S.Item("PC-02", "computer monitor", (1068, 635, 1179, 707)),
        S.Item("PC-03", "computer monitor", (1226, 637, 1343, 711)),
        S.Item("PC-04", "computer monitor", (1402, 636, 1532, 715)),
    ]),
    "classroom": ("data/rooms/RTFX0TQHXko.jpg", [
        S.Item("MON-01", "computer monitor", (786, 706, 989, 887)),
        S.Item("CH-01", "chair", (387, 895, 619, 1060)),
        S.Item("CH-02", "chair", (947, 921, 1157, 1060)),
        S.Item("WB-01", "whiteboard", (514, 381, 1504, 607)),
    ]),
}
EVENTS = [("present", 0.58), ("removed", 0.15), ("covered", 0.13), ("occluded", 0.14)]
TRUTH = {"present": "ok", "removed": "anomaly", "covered": "anomaly", "occluded": "unverifiable"}


def pred_class(state: str) -> str:
    return {"present": "ok", "relocated": "ok", "uncertain": "ok", "candidate_missing": "anomaly",
            "changed": "anomaly", "unverifiable": "unverifiable"}[state]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=40)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--out", default="ml/results/infra_eval.json")
    a = ap.parse_args()
    rng = np.random.default_rng(a.seed)
    cfg = InfraCfg()
    emb = Embedder(cfg.embedder)
    conf = Counter()          # (truth, pred) per item-check
    by_event = Counter()      # (event, pred)
    dim_present = Counter()   # predictions for present items under dim light
    cam = Counter()           # camera turned: detected / missed ; normal: false trigger / ok
    t0 = time.time()
    examples = []
    for room, (path, items) in ROOMS.items():
        base = cv2.imread(str(ROOT / path))
        h, w = base.shape[:2]
        det = OpenVocabDetector(cfg.open_vocab, sorted({i.class_name for i in items}), cfg.open_vocab_conf, cfg.open_vocab_imgsz)
        refs = [S.realism(base, rng, gamma=g) for g in (1.0, 0.85, 1.15)]
        ver = ItemVerifier([(i.id, i.class_name, i.norm(w, h)) for i in items], refs, emb, det, cfg)
        for k in range(a.n):
            ev = {i.id: rng.choice([e for e, _ in EVENTS], p=[p for _, p in EVENTS]) for i in items}
            img = base.copy()
            persons = []
            for i in items:
                if ev[i.id] == "removed":
                    img = S.remove(img, i.box)
            for i in items:
                if ev[i.id] == "covered":
                    img = S.cover(img, i.box, seed=int(rng.integers(1e6)))
            for i in items:
                if ev[i.id] == "occluded":
                    img, pb = S.occlude(img, i.box)
                    persons.append(pb)
            dim = rng.random() < 0.15
            img = S.realism(img, rng, gamma=float(rng.uniform(1.6, 2.0)) if dim else None)
            turned = rng.random() < 0.08
            if turned:
                img = S.turn_camera(img, deg=float(rng.uniform(6, 12)) * rng.choice([-1, 1]), shift=float(rng.uniform(0.05, 0.1)))
            res = ver.check(img, persons)
            if turned:
                cam["turned_detected" if not res.camera_ok else "turned_missed"] += 1
                continue
            cam["normal_false_trigger" if not res.camera_ok else "normal_ok"] += 1
            if not res.camera_ok:
                continue
            for r in res.items:
                t, p = TRUTH[ev[r.id]], pred_class(r.state)
                conf[(t, p)] += 1
                by_event[(ev[r.id], p)] += 1
                if dim and ev[r.id] == "present":
                    dim_present[p] += 1
                if t != p and len(examples) < 12:
                    examples.append(dict(room=room, snap=k, item=r.id, event=ev[r.id], dim=dim, state=r.state, sim=r.sim))
        print(f"{room}: done ({time.time() - t0:.0f}s)", flush=True)

    tp = conf[("anomaly", "anomaly")]
    fp = sum(conf[(t, "anomaly")] for t in ("ok", "unverifiable"))
    fn = sum(conf[("anomaly", p)] for p in ("ok", "unverifiable"))
    present_n = sum(conf[("ok", p)] for p in ("ok", "anomaly", "unverifiable"))
    occl_n = sum(conf[("unverifiable", p)] for p in ("ok", "anomaly", "unverifiable"))
    fa_rate = conf[("ok", "anomaly")] / max(present_n, 1)
    out = dict(
        dataset=f"{a.n} randomised snapshots x {len(ROOMS)} rooms (Unsplash photos + ml/sim events), seed {a.seed}",
        checks=sum(conf.values()),
        anomaly_precision=round(tp / max(tp + fp, 1), 3),
        anomaly_recall=round(tp / max(tp + fn, 1), 3),
        false_alarm_rate_present=round(fa_rate, 4),
        est_alert_false_alarm_rate=round(fa_rate ** 3, 6),   # persistence rule: 3 consecutive anomalous checks (independence assumed)
        occlusion_handled=round(conf[("unverifiable", "unverifiable")] / max(occl_n, 1), 3),
        occlusion_false_alarms=conf[("unverifiable", "anomaly")],
        dim_light_present=dict(dim_present),
        camera=dict(cam),
        confusion={f"{t}->{p}": n for (t, p), n in sorted(conf.items())},
        by_event={f"{e}->{p}": n for (e, p), n in sorted(by_event.items())},
        error_examples=examples,
        seconds=round(time.time() - t0),
    )
    Path(ROOT / a.out).parent.mkdir(parents=True, exist_ok=True)
    (ROOT / a.out).write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k not in ("error_examples", "by_event")}, indent=1))


if __name__ == "__main__":
    main()
