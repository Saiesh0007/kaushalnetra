"""Delete all synthetic fleet centres (simulated=True) and their data, keeping the AI-pipeline demo centres."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sqlalchemy import delete, select  # noqa: E402

from server.app import db as D  # noqa: E402

with D.SessionLocal() as s:
    ids = list(s.scalars(select(D.Centre.id).where(D.Centre.simulated.is_(True))))
    for m in (D.OccupancyWindow, D.ItemCheck, D.ItemUsage, D.TamperEvent, D.Alert, D.TrainingSession, D.InventoryItem, D.Camera, D.DeviceStat):
        s.execute(delete(m).where(m.centre_id.in_(ids)))
    s.execute(delete(D.Centre).where(D.Centre.id.in_(ids)))
    s.commit()
    print(f"removed {len(ids)} synthetic centres")
