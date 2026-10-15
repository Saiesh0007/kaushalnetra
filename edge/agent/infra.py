"""Equipment verification against registered reference views (Design.md §3).

Pipeline per check frame: ORB alignment -> warp item boxes -> occlusion / darkness gate ->
DINOv2 similarity to reference crops -> open-vocabulary detector confirmation -> fusion -> relocation check.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np

log = logging.getLogger("infra")

MEAN = np.array([0.485, 0.456, 0.406], dtype=np.float32)
STD = np.array([0.229, 0.224, 0.225], dtype=np.float32)


# ---------------------------------------------------------------- models
class Embedder:
    """DINOv2-small CLS embeddings (384-d, L2-normalised). Sensitive to *this* object, not just its class."""

    def __init__(self, name: str = "facebook/dinov2-small") -> None:
        import torch
        from transformers import AutoModel

        self.torch = torch
        self.model = AutoModel.from_pretrained(name).eval()
        self._lock = threading.Lock()

    def __call__(self, crops: list[np.ndarray]) -> np.ndarray:
        batch = np.stack([self._prep(c) for c in crops])
        with self._lock, self.torch.inference_mode():
            out = self.model(pixel_values=self.torch.from_numpy(batch)).pooler_output.numpy()
        return out / np.linalg.norm(out, axis=1, keepdims=True)

    @staticmethod
    def _prep(crop: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(clahe(cv2.resize(crop, (224, 224), interpolation=cv2.INTER_AREA)), cv2.COLOR_BGR2RGB)
        return ((rgb.astype(np.float32) / 255.0 - MEAN) / STD).transpose(2, 0, 1)


class OpenVocabDetector:
    """YOLO-World with the centre's sanctioned inventory as its vocabulary."""

    def __init__(self, weights: str, classes: list[str], conf: float = 0.12, imgsz: int = 960) -> None:
        from ultralytics import YOLOWorld

        self.model = YOLOWorld(weights)
        self.model.set_classes(classes)
        self.conf, self.imgsz = conf, imgsz
        self._lock = threading.Lock()

    def __call__(self, frame: np.ndarray) -> list[tuple[str, tuple[float, float, float, float], float]]:
        with self._lock:
            r = self.model.predict(frame, conf=self.conf, imgsz=self.imgsz, verbose=False)[0]
        return [(r.names[int(c)], tuple(map(float, b)), float(p))
                for b, c, p in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy(), r.boxes.conf.cpu().numpy())]


# ---------------------------------------------------------------- helpers
def clahe(img: np.ndarray) -> np.ndarray:
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
    lab[..., 0] = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(lab[..., 0])
    return cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)


def crop(frame: np.ndarray, box, pad: float = 0.10) -> np.ndarray:
    h, w = frame.shape[:2]
    x1, y1, x2, y2 = box
    px, py = (x2 - x1) * pad, (y2 - y1) * pad
    a, b, c, d = int(max(0, x1 - px)), int(max(0, y1 - py)), int(min(w, x2 + px)), int(min(h, y2 + py))
    return frame[b:max(d, b + 2), a:max(c, a + 2)]


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def overlap_frac(item, other) -> float:
    """Fraction of `item` covered by `other`."""
    ix = max(0.0, min(item[2], other[2]) - max(item[0], other[0]))
    iy = max(0.0, min(item[3], other[3]) - max(item[1], other[1]))
    area = (item[2] - item[0]) * (item[3] - item[1])
    return ix * iy / area if area > 0 else 0.0


def augment(img: np.ndarray, rng: np.random.Generator) -> list[np.ndarray]:
    """Plausible day-to-day variation of a reference view, used for self-calibration (simulated burn-in)."""
    out = []
    for g in (0.75, 1.3):
        out.append(np.clip(((img / 255.0) ** g) * 255, 0, 255).astype(np.uint8))
    out.append(np.clip(img + rng.normal(0, 6, img.shape), 0, 255).astype(np.uint8))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 35])
    out.append(cv2.imdecode(buf, cv2.IMREAD_COLOR))
    M = np.float32([[1, 0, rng.integers(-4, 5)], [0, 1, rng.integers(-4, 5)]])
    out.append(cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE))
    out.append(cv2.GaussianBlur(img, (5, 5), 1.2))
    return out


# ---------------------------------------------------------------- verifier
@dataclass
class ItemRef:
    id: str
    class_name: str
    box: tuple[float, float, float, float]          # pixels in the reference frame
    refs: np.ndarray | None = None                  # (k, 384)
    t_present: float = 0.0
    t_missing: float = 0.0
    ref_brightness: float = 0.0


@dataclass
class ItemResult:
    id: str
    state: str
    sim: float | None
    det_conf: float | None
    box: tuple[float, float, float, float]
    reason: str = ""


@dataclass
class CheckResult:
    camera_ok: bool
    inliers: int
    items: list[ItemResult] = field(default_factory=list)


class ItemVerifier:
    def __init__(self, items: list[tuple[str, str, list[float]]], ref_frames: list[np.ndarray], embedder: Embedder,
                 detector: OpenVocabDetector | None, cfg) -> None:
        self.cfg, self.emb, self.det = cfg, embedder, detector
        self.ref = ref_frames[0]
        h, w = self.ref.shape[:2]
        self.size = (w, h)
        self.orb = cv2.ORB_create(nfeatures=cfg.orb_features)
        self.ref_kp, self.ref_desc = self.orb.detectAndCompute(cv2.cvtColor(self.ref, cv2.COLOR_BGR2GRAY), None)
        self.matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        self.items = [ItemRef(i, c, (b[0] * w, b[1] * h, b[2] * w, b[3] * h)) for i, c, b in items]
        self._calibrate(ref_frames)

    def _calibrate(self, ref_frames: list[np.ndarray]) -> None:
        rng = np.random.default_rng(0)
        for it in self.items:
            ref_crops = [crop(f, it.box) for f in ref_frames]
            it.refs = self.emb(ref_crops)
            it.ref_brightness = float(np.mean([cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).mean() for c in ref_crops]))
            variants = [v for f in ref_frames for v in augment(crop(f, it.box), rng)]
            sims = (self.emb(variants) @ it.refs.T).max(axis=1)
            it.t_present = float(max(self.cfg.sim_floor, np.percentile(sims, 1) - self.cfg.calib_margin))
            it.t_missing = it.t_present - self.cfg.hysteresis
            log.info("calibrated %s: variant sims %.3f..%.3f -> t_present=%.3f t_missing=%.3f",
                     it.id, sims.min(), sims.max(), it.t_present, it.t_missing)

    # -------------------------------------------------- alignment (camera-moved check)
    def align(self, frame: np.ndarray) -> tuple[np.ndarray | None, int]:
        g = cv2.cvtColor(cv2.resize(frame, self.size), cv2.COLOR_BGR2GRAY)
        kp, desc = self.orb.detectAndCompute(g, None)
        if desc is None or self.ref_desc is None or len(kp) < 10:
            return None, 0
        pairs = self.matcher.knnMatch(self.ref_desc, desc, k=2)
        good = [m for m, n in (p for p in pairs if len(p) == 2) if m.distance < 0.75 * n.distance]
        if len(good) < self.cfg.min_inliers:
            return None, len(good)
        src = np.float32([self.ref_kp[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dst = np.float32([kp[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        H, mask = cv2.findHomography(src, dst, cv2.RANSAC, 4.0)
        inliers = int(mask.sum()) if mask is not None else 0
        if H is None or inliers < self.cfg.min_inliers:
            return None, inliers
        # a camera that was turned still matches the wall; require the scene to stay where it was registered
        corners = np.float32([[0, 0], [self.size[0], 0], [self.size[0], self.size[1]], [0, self.size[1]]]).reshape(-1, 1, 2)
        drift = float(np.abs(cv2.perspectiveTransform(corners, H) - corners).max()) / self.size[0]
        if drift > self.cfg.max_drift:
            return None, inliers
        return H, inliers

    @staticmethod
    def _warp(box, H) -> tuple[float, float, float, float]:
        pts = np.float32([[box[0], box[1]], [box[2], box[1]], [box[2], box[3]], [box[0], box[3]]]).reshape(-1, 1, 2)
        p = cv2.perspectiveTransform(pts, H).reshape(-1, 2)
        return float(p[:, 0].min()), float(p[:, 1].min()), float(p[:, 0].max()), float(p[:, 1].max())

    # -------------------------------------------------- the check
    def check(self, frame: np.ndarray, person_boxes: list) -> CheckResult:
        frame = cv2.resize(frame, self.size)  # person boxes must already be in this frame's scale
        H, inliers = self.align(frame)
        if H is None:
            return CheckResult(False, inliers)

        boxes = [self._warp(it.box, H) for it in self.items]
        dets = self.det(frame) if self.det else []
        crops, idx, results = [], [], {}
        scene_dark = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()) < self.cfg.dark_scene
        for k, (it, box) in enumerate(zip(self.items, boxes)):
            occ = max((overlap_frac(box, p) for p in person_boxes), default=0.0)
            c = crop(frame, box)
            if occ >= self.cfg.occlusion_frac:
                results[k] = ItemResult(it.id, "unverifiable", None, None, box, f"occluded {occ:.0%}")
            elif scene_dark and float(cv2.cvtColor(c, cv2.COLOR_BGR2GRAY).mean()) < self.cfg.dark_ratio * it.ref_brightness:
                results[k] = ItemResult(it.id, "unverifiable", None, None, box, "too dark")
            else:
                crops.append(c)
                idx.append(k)
        sims = (self.emb(crops) @ np.concatenate([self.items[k].refs for k in idx]).T) if crops else None

        col = 0
        for row, k in enumerate(idx):
            it, box = self.items[k], boxes[k]
            n = len(it.refs)
            sim = float(sims[row, col:col + n].max())
            col += n
            hits = [p for cls, b, p in dets if cls == it.class_name and iou(b, box) >= self.cfg.det_iou]
            det_conf = max(hits, default=0.0)
            if sim >= it.t_present:
                state = "present"
            elif sim >= it.t_missing:
                state = "present" if det_conf else "uncertain"
            else:
                state = "changed" if det_conf else "candidate_missing"
            results[k] = ItemResult(it.id, state, round(sim, 3), round(det_conf, 3), box)

        # relocation: a same-class detection that matches no registered position means the item moved, not vanished
        # each stray explains at most one missing item: the candidate whose reference views it resembles most
        for cls in {it.class_name for it in self.items}:
            cands = [k for k, r in results.items() if r.state == "candidate_missing" and self.items[k].class_name == cls]
            own = [boxes[j] for j, it in enumerate(self.items) if it.class_name == cls]
            strays = [b for c, b, p in dets if c == cls and max((iou(b, o) for o in own), default=0) < 0.1]
            if not cands or not strays:
                continue
            emb = self.emb([crop(frame, b) for b in strays])
            used_s, used_k = set(), set()
            pairs = []
            for s in range(len(strays)):
                sims_k = {k: float((emb[s] @ self.items[k].refs.T).max()) for k in cands}
                best = max(sims_k.values())
                sx, sy = (strays[s][0] + strays[s][2]) / 2, (strays[s][1] + strays[s][3]) / 2
                for k, sim in sims_k.items():
                    # identical models are indistinguishable by appearance: among near-ties, the nearest item moved
                    bx, by = (boxes[k][0] + boxes[k][2]) / 2, (boxes[k][1] + boxes[k][3]) / 2
                    tie = sim >= best - self.cfg.reloc_tie
                    pairs.append((tie, -((sx - bx) ** 2 + (sy - by) ** 2) if tie else sim, sim, s, k))
            for _, _, sim, s, k in sorted(pairs, reverse=True):
                if s in used_s or k in used_k or sim < self.cfg.sim_floor:  # new surroundings lower the score
                    continue
                used_s.add(s)
                used_k.add(k)
                results[k].state = "relocated"
                results[k].reason = f"matched (sim {sim:.2f}) at unregistered position {[round(v) for v in strays[s]]}"
        return CheckResult(True, inliers, [results[k] for k in range(len(self.items))])
