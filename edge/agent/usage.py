"""Equipment usage evidence: "apparent operability" (Design.md §4).

During sessions, an item counts as *in use* in a sample when a person occupies its working area (the item box
widened and extended towards where a user sits). Boxes are re-aligned to the reference view each sample, so slight
camera shake does not matter. Output per item per session: interaction minutes out of observed minutes.
We report evidence of use, never "working/broken" (Memory.md D-009).
"""
from __future__ import annotations

from collections import defaultdict

from .infra import ItemVerifier, overlap_frac


def working_area(box, w: int, h: int) -> tuple[float, float, float, float]:
    x1, y1, x2, y2 = box
    bw, bh = x2 - x1, y2 - y1
    return max(0, x1 - 0.6 * bw), y1, min(w, x2 + 0.6 * bw), min(h, y2 + 1.5 * bh)


class UsageTracker:
    def __init__(self, verifier: ItemVerifier, min_overlap: float = 0.12, max_drift: float = 0.3) -> None:
        self.v = verifier
        self.max_drift = max_drift   # usage only needs boxes mapped correctly; "camera moved" is judged by the tamper check
        self.min_overlap = min_overlap
        self.engaged: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))   # session -> item -> samples
        self.observed: dict[str, int] = defaultdict(int)                                     # session -> aligned samples

    def add(self, session_ref: str, frame, person_boxes_ref_scale: list) -> None:
        H, _ = self.v.align(frame, self.max_drift)
        if H is None:
            return  # camera moved / unreadable: no usage claim either way
        w, h = self.v.size
        self.observed[session_ref] += 1
        for it in self.v.items:
            area = working_area(self.v._warp(it.box, H), w, h)
            if any(overlap_frac(area, p) >= self.min_overlap for p in person_boxes_ref_scale):
                self.engaged[session_ref][it.id] += 1

    def pop(self, session_ref: str, interval_s: float) -> list[tuple[str, float, float]]:
        """(item_id, interaction_min, observed_min) for a finished session."""
        n = self.observed.pop(session_ref, 0)
        eng = self.engaged.pop(session_ref, {})
        if not n:
            return []
        obs = n * interval_s / 60
        return [(it.id, round(eng.get(it.id, 0) * interval_s / 60, 1), round(obs, 1)) for it in self.v.items]
