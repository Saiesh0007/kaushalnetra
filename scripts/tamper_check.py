"""Run only the tamper detector over a clip (fast regression check, no server)."""
import sys
from edge.agent import config as C
from edge.agent.capture import iter_samples
from edge.agent.tamper import TamperDetector
cfg = C.load(sys.argv[1])
for cam in cfg.cameras:
    t = TamperDetector(cfg.tamper)
    segs = cam.segments or [C.SegmentCfg(source=cam.source, start_time=cam.start_time)]
    for seg in segs:
        for s in iter_samples(seg.source, cfg.sampling.interval_s, seg.start_time, False, cam.time_scale):
            for kind, d in t.check(s.ts, s.frame):
                print(f"{cfg.centre.code} {s.ts:%m-%d %H:%M:%S} {kind} {d}")
print(cfg.centre.code, "done")
