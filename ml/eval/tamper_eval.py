"""Tamper-detection accuracy: planted tamper episodes must be caught; clean footage must not trigger.

Positives: clips with known tampered intervals (built by ffmpeg, see configs/centres/demo_d.yaml, tamper_test.yaml).
Negatives: clean clips (all other footage). Reports per-type detection and false triggers per hour of footage.

    python ml/eval/tamper_eval.py
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from edge.agent.capture import iter_samples  # noqa: E402
from edge.agent.config import TamperCfg  # noqa: E402
from edge.agent.tamper import TamperDetector  # noqa: E402

T0 = datetime(2026, 10, 1, 10, 0, tzinfo=timezone(timedelta(hours=5, minutes=30)))
# (clip, sample interval in clip seconds, [(kind, start_s, end_s)] in clip seconds)
CLIPS = [
    ("data/stock/centre_d_tamper.mp4", 1.0, [("looped", 21, 31), ("frozen", 31, 38), ("covered", 38, 42), ("looped", 42, 53)]),  # 10s a | 11s b | a again | 7s still | 4s black | b again
    ("data/samples/tamper_test.mp4", 2.0, [("looped", 70, 110), ("frozen", 110, 130), ("covered", 130, 140), ("looped", 140, 170)]),
    ("data/stock/35954.mp4", 1.0, []), ("data/stock/35968.mp4", 1.0, []), ("data/stock/24099.mp4", 1.0, []),
    ("data/stock/23231.mp4", 1.0, []), ("data/stock/24259.mp4", 1.0, []), ("data/stock/23232.mp4", 1.0, []),
    ("data/stock/28315.mp4", 1.0, []), ("data/stock/28319.mp4", 1.0, []), ("data/samples/vtest.avi", 1.0, []),
]
# a covered lens also has no sensor noise, so "frozen" during a covered interval is a correct co-detection
COMPATIBLE = {"covered": {"covered", "frozen"}}


def main() -> None:
    cfg = TamperCfg()
    planted, caught, false_triggers, clean_seconds, rows = 0, 0, 0, 0.0, []
    per_kind: dict[str, list[int]] = {}
    for clip, step, episodes in CLIPS:
        det = TamperDetector(cfg)
        fired = []
        last_t = 0.0
        for s in iter_samples(str(ROOT / clip), step, T0):
            t = (s.ts - T0).total_seconds()
            last_t = t
            fired += [(kind, t) for kind, _ in det.check(s.ts, s.frame)]
        matched = set()
        for kind, t in fired:
            ok = any(t >= a - 0.01 and t <= b + 8 * step and (kind == k or kind in COMPATIBLE.get(k, ())) for k, a, b in episodes)
            if not ok:
                false_triggers += 1
            for i, (k, a, b) in enumerate(episodes):
                if kind == k and a - 0.01 <= t <= b + 8 * step:
                    matched.add(i)
        for i, (k, a, b) in enumerate(episodes):
            planted += 1
            per_kind.setdefault(k, [0, 0])[1] += 1
            if i in matched:
                caught += 1
                per_kind[k][0] += 1
        dirty = sum(b - a for _, a, b in episodes)
        clean_seconds += max(0.0, last_t + step - dirty)
        rows.append(dict(clip=clip, episodes=len(episodes), fired=[f"{k}@{t:.0f}s" for k, t in fired]))
        print(clip, rows[-1]["fired"], flush=True)
    out = dict(planted_episodes=planted, detected=caught, detection_rate=round(caught / max(planted, 1), 3),
               per_type={k: f"{v[0]}/{v[1]}" for k, v in per_kind.items()},
               false_triggers=false_triggers, clean_footage_minutes=round(clean_seconds / 60, 1),
               note="clean footage = all clips outside planted intervals; sampling 1 frame per clip second (2 s for tamper_test)",
               clips=rows)
    (ROOT / "ml/results").mkdir(parents=True, exist_ok=True)
    (ROOT / "ml/results/tamper_eval.json").write_text(json.dumps(out, indent=1))
    print(json.dumps({k: v for k, v in out.items() if k != "clips"}, indent=1))


if __name__ == "__main__":
    main()
