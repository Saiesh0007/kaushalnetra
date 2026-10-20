"""SQLAlchemy models (Design.md §7). SQLite for the prototype; datetimes stored as naive UTC."""
from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

VAR_DIR = Path(os.environ.get("KNETRA_VAR", Path(__file__).resolve().parents[1] / "var"))
VAR_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR = VAR_DIR / "thumbs"
THUMB_DIR.mkdir(exist_ok=True)

engine = create_engine(f"sqlite:///{VAR_DIR / 'kaushalnetra.db'}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(engine, expire_on_commit=False)
DATA_VERSION = [0]   # bumped on every commit, so read caches know when to recompute


@event.listens_for(SessionLocal, "after_commit")
def _bump_version(_session) -> None:
    DATA_VERSION[0] += 1


def utc(dt: datetime) -> datetime:
    """Normalise any datetime to naive UTC for storage."""
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Centre(Base):
    __tablename__ = "centre"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(64))
    district: Mapped[str] = mapped_column(String(64), default="")
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    scheme: Mapped[str] = mapped_column(String(64), default="")
    trade: Mapped[str] = mapped_column(String(64), default="")
    sanctioned_seats: Mapped[int] = mapped_column(Integer)
    simulated: Mapped[bool] = mapped_column(Boolean, default=False)


class Camera(Base):
    __tablename__ = "camera"
    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    cam_key: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200), default="")
    coverage: Mapped[float] = mapped_column(Float, default=1.0)
    mode: Mapped[str] = mapped_column(String(16), default="edge")
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class InventoryItem(Base):
    __tablename__ = "inventory_item"
    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(64))
    class_name: Mapped[str] = mapped_column(String(64))
    description: Mapped[str] = mapped_column(String(200), default="")
    cam_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    bbox: Mapped[list | None] = mapped_column(JSON, nullable=True)
    camera_verifiable: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingSession(Base):
    __tablename__ = "training_session"
    id: Mapped[int] = mapped_column(primary_key=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    session_ref: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    batch: Mapped[str] = mapped_column(String(64), default="")
    start: Mapped[datetime] = mapped_column(DateTime)
    end: Mapped[datetime] = mapped_column(DateTime)
    claimed_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    claim_source: Mapped[str] = mapped_column(String(32), default="")


class OccupancyWindow(Base):
    __tablename__ = "occupancy_window"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    cam_key: Mapped[str] = mapped_column(String(64))
    session_ref: Mapped[str] = mapped_column(String(128), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    ts_end: Mapped[datetime] = mapped_column(DateTime)
    count_median: Mapped[float] = mapped_column(Float)
    count_p90: Mapped[float] = mapped_column(Float)
    n_frames: Mapped[int] = mapped_column(Integer)
    thumb_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ItemCheck(Base):
    __tablename__ = "item_check"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(64), index=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    state: Mapped[str] = mapped_column(String(32))
    sim: Mapped[float | None] = mapped_column(Float, nullable=True)
    det_conf: Mapped[float | None] = mapped_column(Float, nullable=True)
    thumb_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ItemUsage(Base):
    __tablename__ = "item_usage"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    item_key: Mapped[str] = mapped_column(String(64), index=True)
    session_ref: Mapped[str] = mapped_column(String(128))
    ts: Mapped[datetime] = mapped_column(DateTime)
    interaction_min: Mapped[float] = mapped_column(Float)
    observed_min: Mapped[float] = mapped_column(Float)


class TamperEvent(Base):
    __tablename__ = "tamper_event"
    id: Mapped[int] = mapped_column(primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    cam_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    ts: Mapped[datetime] = mapped_column(DateTime)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    thumb_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class Alert(Base):
    __tablename__ = "alert"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    severity: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16), default="open")
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text, default="")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)
    opened_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    assignee: Mapped[str | None] = mapped_column(String(100), nullable=True)
    resolution_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class DeviceStat(Base):
    __tablename__ = "device_stat"
    centre_id: Mapped[int] = mapped_column(ForeignKey("centre.id"), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(64))
    last_heartbeat: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    bytes_sent: Mapped[int] = mapped_column(Integer, default=0)
    raw_video_bytes: Mapped[int] = mapped_column(Integer, default=0)
    queue_depth: Mapped[int] = mapped_column(Integer, default=0)
    events_received: Mapped[int] = mapped_column(Integer, default=0)
    uptime_pct: Mapped[float] = mapped_column(Float, default=1.0)
    mode: Mapped[str] = mapped_column(String(16), default="edge")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(64))
    entity: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(64))
    at: Mapped[datetime] = mapped_column(DateTime, default=now)
    diff: Mapped[dict] = mapped_column(JSON, default=dict)


def init_db() -> None:
    Base.metadata.create_all(engine)
