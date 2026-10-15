"""Edge agent entry point.

    python -m edge.agent --config configs/centres/demo_a.yaml [--realtime] [--no-register]
"""
from __future__ import annotations

import argparse
import logging
import threading
import time
import uuid
from datetime import datetime

import cv2
import httpx

from common.schemas import CameraSpec, Heartbeat, ItemCheck, OccupancyWindow, Tamper

from . import config as C
from .attendance import OccupancyAggregator, Zone
from .capture import IST, iter_samples
from .detect import PersonDetector
from .infra import Embedder, ItemVerifier, OpenVocabDetector
from .outbox import Outbox
from .privacy import evidence_jpeg
from .tamper import TamperDetector

log = logging.getLogger("agent")


class CameraWorker:
    def __init__(self, cfg: C.AgentCfg, cam: C.CameraCfg, detector: PersonDetector, outbox: Outbox, realtime: bool,
                 infra_models: tuple | None = None) -> None:
        self.cfg, self.cam, self.det, self.outbox, self.realtime = cfg, cam, detector, outbox, realtime
        self.verifier: ItemVerifier | None = None
        items = [(i.id, i.class_name, i.bbox) for i in cfg.centre.items if i.camera_id == cam.id and i.bbox]
        if cam.reference_images and items and infra_models:
            refs = [cv2.imread(p) for p in cam.reference_images]
            self.verifier = ItemVerifier(items, [r for r in refs if r is not None], *infra_models, cfg.infra)
        self.slot: int | None = None
        self.slot_best: tuple | None = None   # (n_people, ts, frame, dets) of the emptiest frame in the current slot
        self.zone = Zone(cam.training_zone, cam.anchor)
        self.tamper = TamperDetector(cfg.tamper)
        self.agg = OccupancyAggregator(cfg.sampling.window_s, self._emit_window)
        self.raw_bytes = 0
        self.frames = 0
        self.latest_jpeg: bytes | None = None   # blurred preview for the local live view

    def _thumb(self, frame, dets, counted) -> bytes:
        zone = self.zone

        def overlay(img, scale):
            h, w = img.shape[:2]
            cv2.polylines(img, [zone.poly(w, h)], True, (255, 200, 0), 1)
            for d in dets:
                color = (0, 200, 0) if d in counted else (120, 120, 120)
                cv2.rectangle(img, (int(d.x1 * scale), int(d.y1 * scale)), (int(d.x2 * scale), int(d.y2 * scale)), color, 1)
            cv2.rectangle(img, (0, 0), (w, 18), (0, 0, 0), -1)
            cv2.putText(img, f"{self.cam.id}  count={len(counted)}", (4, 13), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)

        return evidence_jpeg(frame, [d.box for d in dets], self.cfg.privacy.thumb_width, self.cfg.privacy.jpeg_quality, overlay)

    def _eid(self, *parts: str) -> str:
        """Deterministic event id: re-processing the same footage never duplicates events."""
        return str(uuid.uuid5(uuid.NAMESPACE_URL, "|".join((self.cfg.device_id, self.cam.id, *parts))))

    def _store_thumb(self, data: bytes) -> str:
        tid = uuid.uuid4().hex
        self.outbox.put_thumb(tid, data)
        return tid

    def _emit_window(self, w, med, p90) -> None:
        tid = self._store_thumb(w.best_thumb) if w.best_thumb else None
        self.outbox.put(OccupancyWindow(event_id=self._eid("occ", w.session_ref, w.start.isoformat()), camera_id=self.cam.id, ts=w.start, ts_end=w.end, session_ref=w.session_ref,
                                        count_median=med, count_p90=p90, n_frames=len(w.counts), thumb_id=tid))
        log.info("[%s] window %s %s-%s median=%.1f p90=%.1f n=%d", self.cam.id, w.session_ref, f"{w.start:%H:%M}",
                 f"{w.end:%H:%M}", med, p90, len(w.counts))

    def run(self) -> None:
        t0 = time.monotonic()
        for s in iter_samples(self.cam.source, self.cfg.sampling.interval_s, self.cam.start_time, self.realtime):
            self.frames += 1
            self.raw_bytes = s.raw_bytes
            h, w = s.frame.shape[:2]
            dets = self.det(s.frame)
            counted = [d for d in dets if self.zone.contains(d, w, h)]
            thumb = lambda: self._thumb(s.frame, dets, counted)  # noqa: E731  (lazy: only encode when needed)

            for kind, details in self.tamper.check(s.ts, s.frame):
                log.warning("[%s] TAMPER %s %s", self.cam.id, kind, details)
                self.outbox.put(Tamper(event_id=self._eid("tamper", kind, s.ts.isoformat()), camera_id=self.cam.id, ts=s.ts, kind=kind, details=details,
                                       thumb_id=self._store_thumb(thumb())))

            sess = self.cfg.session_at(s.ts)
            if self.verifier is not None:
                self._consider_for_infra(s.ts, s.frame, dets)
            if sess is not None:
                self.agg.add(s.ts, self.cfg.session_ref(sess), sess.start, len(counted), thumb)
            if self.realtime:
                self.latest_jpeg = thumb()
        self.agg.flush()
        self._run_infra_check()
        log.info("[%s] done: %d samples in %.1fs", self.cam.id, self.frames, time.monotonic() - t0)


    # -------------------------------------------------- equipment checks (Design.md §3)
    def _consider_for_infra(self, ts, frame, dets) -> None:
        """Keep the emptiest frame of each check slot; check it when the slot closes."""
        slot = int(ts.timestamp() // self.cfg.infra.check_interval_s)
        if self.slot is not None and slot != self.slot:
            self._run_infra_check()
        self.slot = slot
        if self.slot_best is None or len(dets) < self.slot_best[0]:
            self.slot_best = (len(dets), ts, frame, dets)

    def _run_infra_check(self) -> None:
        if self.verifier is None or self.slot_best is None:
            return
        _, ts, frame, dets = self.slot_best
        self.slot_best = None
        rw, rh = self.verifier.size
        sx, sy = rw / frame.shape[1], rh / frame.shape[0]
        persons = [(d.x1 * sx, d.y1 * sy, d.x2 * sx, d.y2 * sy) for d in dets]
        res = self.verifier.check(frame, persons)
        if not res.camera_ok:
            kind = "camera_moved"
            if kind not in self.tamper.active:
                self.tamper.active.add(kind)
                log.warning("[%s] TAMPER camera_moved (inliers=%d)", self.cam.id, res.inliers)
                self.outbox.put(Tamper(event_id=self._eid("tamper", kind, ts.isoformat()), camera_id=self.cam.id, ts=ts,
                                       kind=kind, details=dict(inliers=res.inliers),
                                       thumb_id=self._store_thumb(self._infra_thumb(frame, dets, []))))
            return
        self.tamper.active.discard("camera_moved")
        for r in res.items:
            # evidence only when something is wrong: "present" costs zero image bytes
            tid = self._store_thumb(self._infra_thumb(frame, dets, [r])) if r.state not in ("present",) else None
            self.outbox.put(ItemCheck(event_id=self._eid("item", r.id, ts.isoformat()), camera_id=self.cam.id, ts=ts,
                                      item_id=r.id, state=r.state, sim=r.sim, det_conf=r.det_conf, thumb_id=tid))
        log.info("[%s] equipment check %s: %s", self.cam.id, f"{ts:%m-%d %H:%M}",
                 ", ".join(f"{r.id}={r.state}({r.sim})" for r in res.items))

    def _infra_thumb(self, frame, dets, results) -> bytes:
        rw = self.verifier.size[0]
        k = frame.shape[1] / rw

        def overlay(img, scale):
            for r in results:
                x1, y1, x2, y2 = (v * k * scale for v in r.box)
                cv2.rectangle(img, (int(x1), int(y1)), (int(x2), int(y2)), (0, 0, 255), 2)
                cv2.putText(img, f"{r.id} {r.state}", (int(x1), max(12, int(y1) - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

        return evidence_jpeg(frame, [d.box for d in dets], 480, self.cfg.privacy.jpeg_quality, overlay)


def register(cfg: C.AgentCfg) -> None:
    spec = cfg.centre.model_copy(update={"cameras": cfg.centre.cameras or [
        CameraSpec(id=c.id, name=c.name, coverage=c.coverage, mode=cfg.mode) for c in cfg.cameras]})
    r = httpx.put(f"{cfg.server.url}/api/v1/registry/centres/{spec.code}", json=spec.model_dump(mode="json"), timeout=10)
    r.raise_for_status()
    log.info("registered centre %s", spec.code)


def main() -> None:
    ap = argparse.ArgumentParser(description="KaushalNetra edge agent")
    ap.add_argument("--config", required=True)
    ap.add_argument("--realtime", action="store_true", help="pace file sources at real speed (live demo)")
    ap.add_argument("--no-register", action="store_true")
    ap.add_argument("--drain-timeout", type=float, default=120)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)

    cfg = C.load(args.config)
    if not args.no_register:
        register(cfg)
    detector = PersonDetector(cfg.model.detector, cfg.model.conf, cfg.model.imgsz)
    outbox = Outbox(cfg.device_id, cfg.centre.code, cfg.server.url, cfg.server.secret, cfg.server.upload_interval_s)
    outbox.start()

    infra_models = None
    if any(c.reference_images for c in cfg.cameras) and cfg.centre.items:
        vocab = sorted({i.class_name for i in cfg.centre.items})
        infra_models = (Embedder(cfg.infra.embedder),
                        OpenVocabDetector(cfg.infra.open_vocab, vocab, cfg.infra.open_vocab_conf, cfg.infra.open_vocab_imgsz) if cfg.infra.open_vocab else None)
    workers = [CameraWorker(cfg, cam, detector, outbox, args.realtime, infra_models) for cam in cfg.cameras]
    threads = [threading.Thread(target=w.run, name=w.cam.id) for w in workers]
    for t in threads:
        t.start()

    def heartbeat() -> None:
        for w in workers:
            outbox.put(Heartbeat(camera_id=w.cam.id, ts=datetime.now(IST),
                                 queue_depth=outbox.depth(), bytes_sent=outbox.bytes_sent(),
                                 raw_video_bytes=sum(x.raw_bytes for x in workers), mode=cfg.mode))

    last_hb = 0.0
    while any(t.is_alive() for t in threads):
        if time.monotonic() - last_hb > cfg.server.heartbeat_interval_s:
            heartbeat()
            last_hb = time.monotonic()
        time.sleep(0.5)
    heartbeat()

    raw = sum(w.raw_bytes for w in workers)
    ok = outbox.drain(args.drain_timeout)
    sent = outbox.bytes_sent()
    log.info("finished. queue drained=%s | uploaded %.1f KB vs %.1f MB raw video (%.0fx reduction)",
             ok, sent / 1024, raw / 1e6, raw / max(sent, 1))
    outbox.close()


if __name__ == "__main__":
    main()
