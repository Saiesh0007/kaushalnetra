"""Edge agent configuration (one YAML per centre, see configs/centres/)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import BaseModel

from common.schemas import CentreSpec


class ServerCfg(BaseModel):
    url: str = "http://127.0.0.1:8000"
    secret: str = "dev-secret"
    upload_interval_s: float = 3.0
    heartbeat_interval_s: float = 30.0


class ModelCfg(BaseModel):
    detector: str = "yolo11n.pt"
    conf: float = 0.30
    imgsz: int = 640


class SamplingCfg(BaseModel):
    interval_s: float = 30.0      # video-time seconds between analysed frames
    window_s: float = 900.0       # occupancy aggregation window


class PrivacyCfg(BaseModel):
    thumb_width: int = 320
    jpeg_quality: int = 60


class TamperCfg(BaseModel):
    frozen_diff: float = 0.15     # mean abs pixel diff below this = no sensor noise = frozen
    frozen_samples: int = 4
    covered_mean: float = 18.0
    covered_std: float = 10.0
    covered_samples: int = 2
    loop_len: int = 5             # consecutive samples that must repeat
    loop_hash_dist: int = 6
    loop_min_motion: int = 12     # summed hash change inside the window; static rooms can't "loop"


class InfraCfg(BaseModel):
    open_vocab: str | None = "yolov8s-worldv2.pt"   # None disables detector confirmation
    open_vocab_imgsz: int = 1280       # small, distant items need the higher input resolution
    open_vocab_conf: float = 0.12
    embedder: str = "facebook/dinov2-small"
    check_interval_s: float = 1800.0   # one check per slot, on the emptiest frame of the slot
    orb_features: int = 1500
    min_inliers: int = 40
    max_drift: float = 0.05            # max corner displacement (fraction of width) before "camera moved"
    occlusion_frac: float = 0.30
    dark_scene: float = 45.0           # frame mean below this = lights off / dim ...
    dark_ratio: float = 0.5            # ... and the item crop below this fraction of its reference brightness
    sim_floor: float = 0.55
    calib_margin: float = 0.03
    hysteresis: float = 0.10
    det_iou: float = 0.30
    reloc_tie: float = 0.05            # appearance similarities this close count as a tie (identical models)


class CameraCfg(BaseModel):
    id: str
    name: str = ""
    source: str
    start_time: datetime | None = None   # wall-clock time of first frame, for recorded files
    coverage: float = 1.0
    training_zone: list[list[float]] = [[0, 0], [1, 0], [1, 1], [0, 1]]   # normalised polygon
    anchor: str = "center"               # "center" or "bottom" of person box
    reference_images: list[str] = []     # registration views; enables equipment checks for this camera


class SessionCfg(BaseModel):
    batch: str
    start: datetime
    end: datetime


class AgentCfg(BaseModel):
    device_id: str
    mode: str = "edge"
    centre: CentreSpec
    server: ServerCfg = ServerCfg()
    model: ModelCfg = ModelCfg()
    sampling: SamplingCfg = SamplingCfg()
    privacy: PrivacyCfg = PrivacyCfg()
    tamper: TamperCfg = TamperCfg()
    infra: InfraCfg = InfraCfg()
    cameras: list[CameraCfg]
    sessions: list[SessionCfg] = []

    def session_at(self, ts: datetime) -> SessionCfg | None:
        for s in self.sessions:
            if s.start <= ts < s.end:
                return s
        return None

    def session_ref(self, s: SessionCfg) -> str:
        return f"{self.centre.code}/{s.batch}/{s.start:%Y-%m-%d}"


def load(path: str | Path) -> AgentCfg:
    path = Path(path)
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    cfg = AgentCfg.model_validate(raw)
    rel = lambda p: p if ("://" in p or Path(p).is_absolute()) else str((path.parent / p).resolve())  # noqa: E731
    for cam in cfg.cameras:  # resolve file paths relative to the config file
        cam.source = rel(cam.source)
        cam.reference_images = [rel(r) for r in cam.reference_images]
    return cfg
