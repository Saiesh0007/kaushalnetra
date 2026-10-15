"""Frame sampling from a video file (recorded time) or a live RTSP stream (wall-clock time)."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterator

import cv2
import numpy as np

IST = timezone(timedelta(hours=5, minutes=30))
LIVE_BITRATE_BPS = 1_000_000  # typical 720p H.264 CCTV stream, used to estimate avoided upload volume


@dataclass
class Sample:
    ts: datetime
    frame: np.ndarray
    raw_bytes: int  # bytes of source video "consumed" so far, i.e. what a full upload would have cost


def iter_samples(source: str, interval_s: float, start_time: datetime | None, realtime: bool = False,
                 time_scale: float = 1.0) -> Iterator[Sample]:
    if source.endswith(".csv"):
        yield from _snapshot_samples(source)
        return
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        raise RuntimeError(f"cannot open source {source}")
    is_file = "://" not in source
    try:
        if is_file:
            yield from _file_samples(cap, source, interval_s, start_time or datetime.now(IST), realtime, time_scale)
        else:
            yield from _live_samples(cap, interval_s)
    finally:
        cap.release()


def _file_samples(cap, source, interval_s, start_time, realtime, time_scale=1.0) -> Iterator[Sample]:
    """`interval_s` is in centre time; with time_scale > 1 a short clip stands in for a longer session."""
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or 1
    size = os.path.getsize(source)
    step = max(1, round(fps * interval_s / time_scale))
    idx = 0
    t0 = time.monotonic()
    while True:
        if not cap.grab():
            return
        if idx % step == 0:
            ok, frame = cap.retrieve()
            if not ok:
                return
            video_t = idx / fps
            if realtime:
                delay = video_t - (time.monotonic() - t0)
                if delay > 0:
                    time.sleep(delay)
            # raw bytes: what streaming this much *centre time* would cost (time-lapse demos stand in for real sessions)
            centre_t = video_t * time_scale
            raw = int(size * min(1.0, (idx + 1) / total)) if time_scale == 1.0 else int(centre_t * LIVE_BITRATE_BPS / 8)
            yield Sample(start_time + timedelta(seconds=centre_t), frame, raw)
        idx += 1


def _live_samples(cap, interval_s) -> Iterator[Sample]:
    t0 = time.monotonic()
    nxt = t0
    while True:
        ok = cap.grab()  # keep draining the buffer so samples are fresh
        if not ok:
            time.sleep(1.0)
            continue
        now = time.monotonic()
        if now >= nxt:
            ok, frame = cap.retrieve()
            if ok:
                yield Sample(datetime.now(IST), frame, int((now - t0) * LIVE_BITRATE_BPS / 8))
            nxt = now + interval_s


def _snapshot_samples(manifest: str) -> Iterator[Sample]:
    """Snapshot mode: a CSV of `ts,path` stills (periodic JPEGs from the camera instead of video)."""
    import csv
    from pathlib import Path

    base = Path(manifest).parent
    with open(manifest, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            frame = cv2.imread(str(base / row["path"]))
            if frame is None:
                continue
            yield Sample(datetime.fromisoformat(row["ts"]), frame, 0)
