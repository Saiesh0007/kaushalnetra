"""Camera-integrity checks (Design.md §5): frozen, looped and covered feeds.

Camera-moved detection lives with the infrastructure alignment step (needs reference frames).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

import cv2
import imagehash
import numpy as np
from PIL import Image

from .config import TamperCfg


class TamperDetector:
    def __init__(self, cfg: TamperCfg, history: int = 240) -> None:
        self.cfg = cfg
        self.prev_gray: np.ndarray | None = None
        self.frozen_run = 0
        self.covered_run = 0
        self.hashes: deque[tuple[datetime, imagehash.ImageHash, float]] = deque(maxlen=history)   # ts, pHash, motion
        self.active: set[str] = set()   # episodes currently open, so each episode is reported once

    def check(self, ts: datetime, frame: np.ndarray) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)

        # covered / blacked out
        mean, std = float(gray.mean()), float(gray.std())
        self.covered_run = self.covered_run + 1 if (mean < self.cfg.covered_mean or std < self.cfg.covered_std) else 0
        out += self._episode("covered", self.covered_run >= self.cfg.covered_samples, dict(mean=round(mean, 1), std=round(std, 1)))

        # frozen: a live sensor always has noise; identical frames mean a still image is being fed
        motion = 0.0
        if self.prev_gray is not None:
            diff = motion = float(cv2.absdiff(gray, self.prev_gray).mean())
            self.frozen_run = self.frozen_run + 1 if diff < self.cfg.frozen_diff else 0
            out += self._episode("frozen", self.frozen_run >= self.cfg.frozen_samples,
                                 dict(mean_abs_diff=round(diff, 3), samples=self.frozen_run))
        self.prev_gray = gray

        # looped: the latest run repeats an earlier run in BOTH appearance (pHash) and motion pattern.
        # Similar-looking live footage (a static class on two days) matches in appearance but not in motion.
        h = imagehash.phash(Image.fromarray(gray))
        self.hashes.append((ts, h, motion))
        out += self._episode("looped", *self._loop_match(ts))
        return out

    def _loop_match(self, now: datetime) -> tuple[bool, dict]:
        c, L = self.cfg, self.cfg.loop_len
        hist = [x for x in self.hashes if (now - x[0]).total_seconds() <= c.loop_history_s]
        if len(hist) < 2 * L + 1:
            return False, {}
        tail = hist[-L:]
        t_hash = [h for _, h, _ in tail]
        t_mot = np.array([m for _, _, m in tail[1:]])
        if sum(t_hash[i] - t_hash[i - 1] for i in range(1, L)) < c.loop_min_motion or t_mot.mean() < c.loop_min_pixel_motion:
            return False, {}
        for start in range(0, len(hist) - 2 * L + 1):
            cand = hist[start:start + L]
            if not all(a - b <= c.loop_hash_dist for (_, a, _), b in zip(cand, t_hash)):
                continue
            c_mot = np.array([m for _, _, m in cand[1:]])
            err = float(np.abs(c_mot - t_mot).sum() / max(t_mot.sum(), 1e-6))
            if err <= c.loop_motion_err:
                return True, dict(matches_footage_from=cand[0][0].isoformat(), window_samples=L,
                                  motion_pattern_error=round(err, 3))
        return False, {}

    def _episode(self, kind: str, on: bool, details: dict) -> list[tuple[str, dict]]:
        if on and kind not in self.active:
            self.active.add(kind)
            return [(kind, details)]
        if not on:
            self.active.discard(kind)
        return []
