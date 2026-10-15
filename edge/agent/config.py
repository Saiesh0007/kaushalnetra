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


class CameraCfg(BaseModel):
    id: str
    name: str = ""
    source: str
    start_time: datetime | None = None   # wall-clock time of first frame, for recorded files
    coverage: float = 1.0
    training_zone: list[list[float]] = [[0, 0], [1, 0], [1, 1], [0, 1]]   # normalised polygon
    anchor: str = "center"               # "center" or "bottom" of person box


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
    for cam in cfg.cameras:  # resolve file sources relative to the config file
        if "://" not in cam.source and not Path(cam.source).is_absolute():
            cam.source = str((path.parent / cam.source).resolve())
    return cfg
