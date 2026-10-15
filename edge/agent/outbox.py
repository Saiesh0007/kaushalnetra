"""Store-and-forward event queue (Architecture.md §5). Survives restarts and network loss.

Tamper events upload first. Thumbnails upload before the events that reference them.
Create the file `edge/var/OFFLINE` to simulate a network cut during demos.
"""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import logging
import sqlite3
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx

from common.schemas import EventBatch

from .capture import IST

log = logging.getLogger("outbox")
VAR = Path(__file__).resolve().parents[1] / "var"
OFFLINE_FLAG = VAR / "OFFLINE"
PRIORITY = {"tamper": 0, "item_check": 1, "occupancy_window": 2, "item_usage": 2, "heartbeat": 3}


class Outbox:
    def __init__(self, device_id: str, centre_code: str, server_url: str, secret: str, interval_s: float) -> None:
        VAR.mkdir(exist_ok=True)
        self.device_id, self.centre_code = device_id, centre_code
        self.url, self.secret, self.interval = server_url.rstrip("/"), secret.encode(), interval_s
        self.db = sqlite3.connect(VAR / f"outbox_{device_id}.db", check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS ev (id TEXT PRIMARY KEY, prio INT, created REAL, body TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS th (id TEXT PRIMARY KEY, created REAL, data BLOB)")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (k TEXT PRIMARY KEY, v INT)")
        self.db.commit()
        self.lock = threading.Lock()
        self.client = httpx.Client(timeout=15)
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)

    # -------------------------------------------------- producer side
    def put(self, event) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO ev VALUES (?,?,?,?)",
                            (event.event_id, PRIORITY.get(event.type, 5), time.time(), event.model_dump_json()))
            self.db.commit()

    def put_thumb(self, thumb_id: str, data: bytes) -> None:
        with self.lock:
            self.db.execute("INSERT OR IGNORE INTO th VALUES (?,?,?)", (thumb_id, time.time(), data))
            self.db.commit()

    def depth(self) -> int:
        with self.lock:
            return self.db.execute("SELECT (SELECT COUNT(*) FROM ev) + (SELECT COUNT(*) FROM th)").fetchone()[0]

    def bytes_sent(self) -> int:
        with self.lock:
            row = self.db.execute("SELECT v FROM meta WHERE k='bytes_sent'").fetchone()
            return row[0] if row else 0

    def _add_bytes(self, n: int) -> None:
        with self.lock:
            self.db.execute("INSERT INTO meta VALUES ('bytes_sent', ?) ON CONFLICT(k) DO UPDATE SET v = v + ?", (n, n))
            self.db.commit()

    # -------------------------------------------------- sender
    def start(self) -> None:
        self.thread.start()

    def drain(self, timeout: float = 60) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if self.depth() == 0:
                return True
            time.sleep(0.5)
        return False

    def close(self) -> None:
        self.stop.set()
        self.thread.join(timeout=5)

    def _sign(self, data: bytes) -> str:
        return hmac.new(self.secret, data, hashlib.sha256).hexdigest()

    def _run(self) -> None:
        while not self.stop.is_set():
            try:
                if not OFFLINE_FLAG.exists():
                    self._send_once()
            except httpx.HTTPError as e:
                log.warning("upload failed, will retry: %s", e)
            except Exception:
                log.exception("sender error")
            self.stop.wait(self.interval)

    def _send_once(self) -> None:
        with self.lock:
            thumbs = self.db.execute("SELECT id, data FROM th ORDER BY created LIMIT 20").fetchall()
        for tid, data in thumbs:
            r = self.client.post(f"{self.url}/api/v1/ingest/thumbnails", data={"thumb_id": tid, "centre_code": self.centre_code},
                                 files={"file": (f"{tid}.jpg", data, "image/jpeg")}, headers={"x-signature": self._sign(data)})
            r.raise_for_status()
            with self.lock:
                self.db.execute("DELETE FROM th WHERE id=?", (tid,))
                self.db.commit()
            self._add_bytes(len(data))

        with self.lock:
            rows = self.db.execute("SELECT id, body FROM ev ORDER BY prio, created LIMIT 200").fetchall()
        if not rows:
            return
        batch = EventBatch(device_id=self.device_id, centre_code=self.centre_code, sent_at=datetime.now(IST),
                           events=[json.loads(b) for _, b in rows])
        raw = batch.model_dump_json().encode()
        body = gzip.compress(raw)
        r = self.client.post(f"{self.url}/api/v1/ingest/events", content=body,
                             headers={"content-type": "application/json", "content-encoding": "gzip",
                                      "x-signature": self._sign(raw)})
        r.raise_for_status()
        with self.lock:
            self.db.executemany("DELETE FROM ev WHERE id=?", [(i,) for i, _ in rows])
            self.db.commit()
        self._add_bytes(len(body))
        log.info("uploaded %d events (%d B gzip), server: %s", len(rows), len(body), r.json())
