"""Person detector wrapper. Loaded once per process (Rules.md §3)."""
from __future__ import annotations

import threading
from dataclasses import dataclass

import numpy as np


@dataclass
class Det:
    x1: float
    y1: float
    x2: float
    y2: float
    conf: float
    cls: int

    @property
    def box(self) -> tuple[float, float, float, float]:
        return self.x1, self.y1, self.x2, self.y2


class PersonDetector:
    def __init__(self, weights: str, conf: float, imgsz: int) -> None:
        from ultralytics import YOLO

        self.model = YOLO(weights)
        self.conf, self.imgsz = conf, imgsz
        self._lock = threading.Lock()

    def __call__(self, frame: np.ndarray) -> list[Det]:
        with self._lock:
            r = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, classes=[0], verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        return [Det(*map(float, b), float(c), int(k)) for b, c, k in zip(xyxy, confs, cls)]
