"""Shared wire schemas between the edge agent and the server (Design.md §10).

Privacy (Rules.md §1): no field here may carry identity, per-person tracks or raw imagery.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


def new_id() -> str:
    return str(uuid.uuid4())


# ---------------------------------------------------------------- events
class _Event(BaseModel):
    event_id: str = Field(default_factory=new_id)
    camera_id: str
    ts: datetime


class OccupancyWindow(_Event):
    type: Literal["occupancy_window"] = "occupancy_window"
    session_ref: str
    ts_end: datetime
    count_median: float
    count_p90: float
    n_frames: int
    thumb_id: str | None = None


ItemState = Literal["present", "uncertain", "changed", "candidate_missing", "relocated", "unverifiable"]


class ItemCheck(_Event):
    type: Literal["item_check"] = "item_check"
    item_id: str
    state: ItemState
    sim: float | None = None
    det_conf: float | None = None
    thumb_id: str | None = None


class ItemUsage(_Event):
    type: Literal["item_usage"] = "item_usage"
    item_id: str
    session_ref: str
    interaction_min: float
    observed_min: float


TamperKind = Literal["frozen", "looped", "covered", "camera_moved", "camera_offline"]


class Tamper(_Event):
    type: Literal["tamper"] = "tamper"
    kind: TamperKind
    details: dict = Field(default_factory=dict)
    thumb_id: str | None = None


class Heartbeat(_Event):
    type: Literal["heartbeat"] = "heartbeat"
    fps: float = 0.0
    queue_depth: int = 0
    bytes_sent: int = 0
    raw_video_bytes: int = 0
    mode: Literal["edge", "snapshot"] = "edge"


Event = Annotated[Union[OccupancyWindow, ItemCheck, ItemUsage, Tamper, Heartbeat], Field(discriminator="type")]


class EventBatch(BaseModel):
    batch_id: str = Field(default_factory=new_id)
    device_id: str
    centre_code: str
    sent_at: datetime
    events: list[Event]


# ---------------------------------------------------------------- registry
class ItemSpec(BaseModel):
    id: str
    class_name: str
    description: str = ""
    camera_id: str | None = None
    bbox: list[float] | None = None  # normalised x1,y1,x2,y2
    camera_verifiable: bool = True


class CameraSpec(BaseModel):
    id: str
    name: str = ""
    coverage: float = 1.0
    mode: Literal["edge", "snapshot"] = "edge"


class CentreSpec(BaseModel):
    code: str
    name: str
    state: str
    district: str = ""
    lat: float
    lon: float
    scheme: str = "PMKVY 4.0"
    trade: str = ""
    sanctioned_seats: int
    cameras: list[CameraSpec] = []
    items: list[ItemSpec] = []
    simulated: bool = False


class ClaimIn(BaseModel):
    centre_code: str
    session_ref: str
    batch: str = ""
    start: datetime
    end: datetime
    claimed_count: int
    source: str = "mis-mock"
