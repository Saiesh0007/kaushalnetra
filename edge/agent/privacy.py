"""The only module allowed to turn frames into stored or transmitted images (Rules.md §1.2).

Every person box is pixelated before anything is encoded. Faces are never located or identified;
the whole body region is destroyed, which also covers the face.
"""
from __future__ import annotations

import cv2
import numpy as np

PIXEL_BLOCKS = 6  # blocks across a person box after pixelation: nothing identifiable survives


def blur_people(frame: np.ndarray, boxes: list[tuple[float, float, float, float]]) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    for x1, y1, x2, y2 in boxes:
        # pad the box: detectors often clip heads
        pw, ph = (x2 - x1) * 0.1, (y2 - y1) * 0.1
        a, b = max(0, int(x1 - pw)), max(0, int(y1 - ph))
        c, d = min(w, int(x2 + pw)), min(h, int(y2 + ph))
        if c - a < 2 or d - b < 2:
            continue
        roi = out[b:d, a:c]
        small = cv2.resize(roi, (PIXEL_BLOCKS, max(1, int(PIXEL_BLOCKS * (d - b) / (c - a)))), interpolation=cv2.INTER_LINEAR)
        out[b:d, a:c] = cv2.resize(small, (c - a, d - b), interpolation=cv2.INTER_NEAREST)
    return out


def evidence_jpeg(frame: np.ndarray, person_boxes: list, width: int = 320, quality: int = 60,
                  overlay=None) -> bytes:
    """Blur, downscale, optionally annotate, then encode. `overlay(img, scale)` draws on the blurred image."""
    safe = blur_people(frame, person_boxes)
    scale = width / safe.shape[1]
    small = cv2.resize(safe, (width, int(safe.shape[0] * scale)), interpolation=cv2.INTER_AREA)
    if overlay is not None:
        overlay(small, scale)
    ok, buf = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, quality])
    if not ok:
        raise RuntimeError("jpeg encode failed")
    return buf.tobytes()
