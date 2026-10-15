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
        self.hashes: deque[tuple[datetime, imagehash.ImageHash]] = deque(maxlen=history)
        self.active: set[str] = set()   # episodes currently open, so each episode is reported once

    def check(self, ts: datetime, frame: np.ndarray) -> list[tuple[str, dict]]:
        out: list[tuple[str, dict]] = []
        gray = cv2.cvtColor(cv2.resize(frame, (320, 180)), cv2.COLOR_BGR2GRAY)

        # covered / blacked out
        mean, std = float(gray.mean()), float(gray.std())
        self.covered_run = self.covered_run + 1 if (mean < self.cfg.covered_mean or std < self.cfg.covered_std) else 0
        out += self._episode("covered", self.covered_run >= self.cfg.covered_samples, dict(mean=round(mean, 1), std=round(std, 1)))

        # frozen: a live sensor always has noise; identical frames mean a still image is being fed
        if self.prev_gray is not None:
            diff = float(cv2.absdiff(gray, self.prev_gray).mean())
            self.frozen_run = self.frozen_run + 1 if diff < self.cfg.frozen_diff else 0
            out += self._episode("frozen", self.frozen_run >= self.cfg.frozen_samples,
                                 dict(mean_abs_diff=round(diff, 3), samples=self.frozen_run))
        self.prev_gray = gray

        # looped: the latest run of hashes repeats an earlier run, and the scene was actually changing
        h = imagehash.phash(Image.fromarray(gray))
        self.hashes.append((ts, h))
        out += self._episode("looped", *self._loop_match())
        return out

    def _loop_match(self) -> tuple[bool, dict]:
        L = self.cfg.loop_len
        hs = [h for _, h in self.hashes]
        if len(hs) < 2 * L + 1:
            return False, {}
        tail = hs[-L:]
        motion = sum(tail[i] - tail[i - 1] for i in range(1, L))
        if motion < self.cfg.loop_min_motion:
            return False, {}
        for start in range(0, len(hs) - 2 * L + 1):
            cand = hs[start:start + L]
            if all(a - b <= self.cfg.loop_hash_dist for a, b in zip(cand, tail)):
                t_then = self.hashes[start][0]
                return True, dict(matches_footage_from=t_then.isoformat(), window_samples=L, motion=int(motion))
        return False, {}

    def _episode(self, kind: str, on: bool, details: dict) -> list[tuple[str, dict]]:
        if on and kind not in self.active:
            self.active.add(kind)
            return [(kind, details)]
        if not on:
            self.active.discard(kind)
        return []
