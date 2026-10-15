"""Simulated centre camera snapshots with exact ground truth (the PS allows "sample/simulated centre footage").

Starts from a real empty-room photo and applies controlled events to registered items:
remove (inpaint), cover (cloth), move, occlude (a real person cut-out), dim lights, camera turned.
Every snapshot also gets camera realism: sensor noise, exposure drift, sub-pixel jitter, JPEG compression.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Item:
    id: str
    class_name: str
    box: tuple[int, int, int, int]   # pixels in the base image

    def norm(self, w: int, h: int) -> list[float]:
        x1, y1, x2, y2 = self.box
        return [round(x1 / w, 4), round(y1 / h, 4), round(x2 / w, 4), round(y2 / h, 4)]


def realism(img: np.ndarray, rng: np.random.Generator, gamma: float | None = None) -> np.ndarray:
    g = gamma if gamma is not None else rng.uniform(0.9, 1.12)
    out = ((img / 255.0) ** g) * 255
    M = np.float32([[1, 0, rng.uniform(-2, 2)], [0, 1, rng.uniform(-2, 2)]])
    out = cv2.warpAffine(out.astype(np.float32), M, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)
    out = np.clip(out + rng.normal(0, 3.0, out.shape), 0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(60, 85))])
    return cv2.imdecode(buf, cv2.IMREAD_COLOR)


def _grow(box, f, w, h):
    x1, y1, x2, y2 = box
    dx, dy = (x2 - x1) * f, (y2 - y1) * f
    return int(max(0, x1 - dx)), int(max(0, y1 - dy)), int(min(w, x2 + dx)), int(min(h, y2 + dy))


def remove(img: np.ndarray, box) -> np.ndarray:
    """Fill the item's area row by row from the pixels either side of it.

    Rooms are dominated by horizontal structure (walls, desk edges), which row interpolation preserves.
    """
    h, w = img.shape[:2]
    x1, y1, x2, y2 = _grow(box, 0.06, w, h)
    out = img.copy().astype(np.float32)
    left = out[y1:y2, max(0, x1 - 6):x1].mean(axis=1)            # (rows, 3)
    right = out[y1:y2, x2:min(w, x2 + 6)].mean(axis=1)
    t = np.linspace(0, 1, x2 - x1, dtype=np.float32)[None, :, None]
    fill = left[:, None, :] * (1 - t) + right[:, None, :] * t
    fill += np.random.default_rng(x1 * 7 + y1).normal(0, 2.5, fill.shape)
    out[y1:y2, x1:x2] = cv2.GaussianBlur(fill, (5, 5), 0)
    return np.clip(out, 0, 255).astype(np.uint8)


def cover(img: np.ndarray, box, seed: int = 0) -> np.ndarray:
    """Drape a cloth: low-frequency folds over a fabric colour (fixed per seed, so it is the same cloth every day)."""
    rng = np.random.default_rng(seed)
    h, w = img.shape[:2]
    x1, y1, x2, y2 = _grow(box, 0.05, w, h)
    bw, bh = x2 - x1, y2 - y1
    colour = np.array(rng.choice([[60, 60, 140], [120, 105, 85], [150, 150, 155], [80, 120, 60]]), np.float32)
    yy, xx = np.mgrid[0:bh, 0:bw].astype(np.float32)
    folds = 0.75 + 0.25 * np.sin(xx / max(bw, 1) * rng.uniform(6, 12) + np.sin(yy / max(bh, 1) * 3) * 2)
    cloth = (colour[None, None, :] * folds[..., None]) + rng.normal(0, 6, (bh, bw, 3))
    out = img.copy()
    out[y1:y2, x1:x2] = np.clip(cloth, 0, 255).astype(np.uint8)
    return out


def move(img: np.ndarray, box, to_xy) -> np.ndarray:
    x1, y1, x2, y2 = box
    patch = img[y1:y2, x1:x2].copy()
    out = remove(img, box)
    tx, ty = to_xy
    out[ty:ty + patch.shape[0], tx:tx + patch.shape[1]] = patch
    return out


@lru_cache(maxsize=1)
def _person_cutout() -> tuple[np.ndarray, np.ndarray]:
    """A standing person cut from a free Mixkit clip, via instance segmentation."""
    from ultralytics import YOLO

    cap = cv2.VideoCapture(str(ROOT / "data/stock/24099.mp4"))
    cap.set(cv2.CAP_PROP_POS_FRAMES, 200)
    ok, frame = cap.read()
    r = YOLO("yolo11n-seg.pt").predict(frame, classes=[0], verbose=False)[0]
    k = int(np.argmax([(b[3] - b[1]) for b in r.boxes.xyxy.tolist()]))   # tallest person
    mask = cv2.resize(r.masks.data[k].numpy(), (frame.shape[1], frame.shape[0])) > 0.5
    x1, y1, x2, y2 = map(int, r.boxes.xyxy[k].tolist())
    return frame[y1:y2, x1:x2].copy(), mask[y1:y2, x1:x2].copy()


def occlude(img: np.ndarray, box) -> tuple[np.ndarray, tuple[int, int, int, int]]:
    """Stand a person in front of the item. Returns image and the person's box."""
    person, mask = _person_cutout()
    x1, y1, x2, y2 = box
    ph = int((y2 - y1) * 3.2)
    pw = int(person.shape[1] * ph / person.shape[0])
    p = cv2.resize(person, (pw, ph))
    m = cv2.resize(mask.astype(np.uint8), (pw, ph)).astype(bool)
    cx = (x1 + x2) // 2
    px1, py1 = max(0, cx - pw // 2), max(0, y1 - ph // 5)
    h, w = img.shape[:2]
    px2, py2 = min(w, px1 + pw), min(h, py1 + ph)
    out = img.copy()
    region = out[py1:py2, px1:px2]
    mm = m[: py2 - py1, : px2 - px1]
    region[mm] = p[: py2 - py1, : px2 - px1][mm]
    return out, (px1, py1, px2, py2)


def turn_camera(img: np.ndarray, deg: float = 9.0, shift: float = 0.08) -> np.ndarray:
    h, w = img.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), deg, 1.08)
    M[0, 2] += shift * w
    return cv2.warpAffine(img, M, (w, h), borderMode=cv2.BORDER_REFLECT)
