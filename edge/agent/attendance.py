"""Head-count inside the training area, aggregated into robust occupancy windows (Design.md §2).

No identities and no tracks are kept: only per-frame counts (Rules.md §1.3–1.4).
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Callable

import cv2
import numpy as np

from .detect import Det


class Zone:
    def __init__(self, norm_polygon: list[list[float]], anchor: str = "center") -> None:
        self.norm = np.array(norm_polygon, dtype=np.float32)
        self.anchor = anchor

    def poly(self, w: int, h: int) -> np.ndarray:
        return (self.norm * np.array([w, h], dtype=np.float32)).astype(np.int32)

    def contains(self, d: Det, w: int, h: int) -> bool:
        x = (d.x1 + d.x2) / 2
        y = d.y2 if self.anchor == "bottom" else (d.y1 + d.y2) / 2
        return cv2.pointPolygonTest(self.poly(w, h), (float(x), float(y)), False) >= 0


@dataclass
class _Window:
    session_ref: str
    start: datetime
    end: datetime
    counts: list[int] = field(default_factory=list)
    best_thumb: bytes | None = None
    best_dist: float = 1e9


class OccupancyAggregator:
    """Collects per-sample counts and emits one window per `window_s` of session time."""

    def __init__(self, window_s: float, emit: Callable[[_Window, float, float], None]) -> None:
        self.window = timedelta(seconds=window_s)
        self.emit = emit
        self.cur: _Window | None = None

    def add(self, ts: datetime, session_ref: str, session_start: datetime, count: int, thumb: Callable[[], bytes]) -> None:
        if self.cur and (self.cur.session_ref != session_ref or ts >= self.cur.end):
            self.flush()
        if self.cur is None:
            k = int((ts - session_start) / self.window)
            start = session_start + k * self.window
            self.cur = _Window(session_ref, start, start + self.window)
        self.cur.counts.append(count)
        # keep the thumbnail closest to the running median as the window's evidence
        med = statistics.median(self.cur.counts)
        if abs(count - med) < self.cur.best_dist:
            self.cur.best_dist = abs(count - med)
            self.cur.best_thumb = thumb()

    def flush(self) -> None:
        w, self.cur = self.cur, None
        if not w or not w.counts:
            return
        med = float(statistics.median(w.counts))
        p90 = float(np.percentile(w.counts, 90))
        self.emit(w, med, p90)
