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
        self.conf, self.imgsz = conf, imgsz
        self._lock = threading.Lock()
        self.onnx = weights.endswith(".onnx")
        if self.onnx:
            # Small hosts: ONNX Runtime runs the same exported YOLO without PyTorch (a fraction of the memory)
            import os

            import onnxruntime as ort

            opts = ort.SessionOptions()
            # containers report the host's cores; on a fractional-CPU host extra threads only fight over the quota
            opts.intra_op_num_threads = opts.inter_op_num_threads = int(os.environ.get("OMP_NUM_THREADS", "0"))
            self.sess = ort.InferenceSession(weights, opts, providers=["CPUExecutionProvider"])
            self.input = self.sess.get_inputs()[0].name
            self.imgsz = self.sess.get_inputs()[0].shape[2]
        else:
            from ultralytics import YOLO

            self.model = YOLO(weights)

    def _onnx(self, frame: np.ndarray, iou: float = 0.7) -> list[Det]:
        import cv2

        # letterbox like Ultralytics: keep aspect ratio, pad to a square with grey
        h, w = frame.shape[:2]
        r = min(self.imgsz / h, self.imgsz / w)
        nh, nw = round(h * r), round(w * r)
        top, left = (self.imgsz - nh) // 2, (self.imgsz - nw) // 2
        canvas = np.full((self.imgsz, self.imgsz, 3), 114, np.uint8)
        canvas[top:top + nh, left:left + nw] = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        x = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
        with self._lock:
            out = self.sess.run(None, {self.input: x})[0][0]   # (4 + classes, anchors): cx, cy, w, h, scores
        scores = out[4]                                       # class 0 = person
        keep = scores >= self.conf
        if not keep.any():
            return []
        cx, cy, bw, bh = out[0][keep], out[1][keep], out[2][keep], out[3][keep]
        s = scores[keep]
        x1, y1 = (cx - bw / 2 - left) / r, (cy - bh / 2 - top) / r
        boxes = np.stack([x1, y1, bw / r, bh / r], 1)
        idx = cv2.dnn.NMSBoxes(boxes.tolist(), s.tolist(), self.conf, iou)
        dets = []
        for i in np.array(idx).flatten():
            bx, by, ww, hh = boxes[i]
            dets.append(Det(float(np.clip(bx, 0, w)), float(np.clip(by, 0, h)), float(np.clip(bx + ww, 0, w)),
                            float(np.clip(by + hh, 0, h)), float(s[i]), 0))
        return dets

    def __call__(self, frame: np.ndarray) -> list[Det]:
        if self.onnx:
            return self._onnx(frame)
        with self._lock:
            r = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, classes=[0], verbose=False)[0]
        if r.boxes is None or len(r.boxes) == 0:
            return []
        xyxy = r.boxes.xyxy.cpu().numpy()
        confs = r.boxes.conf.cpu().numpy()
        cls = r.boxes.cls.cpu().numpy().astype(int)
        return [Det(*map(float, b), float(c), int(k)) for b, c, k in zip(xyxy, confs, cls)]
