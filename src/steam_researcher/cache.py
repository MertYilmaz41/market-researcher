"""Tiny SQLite key/value cache with per-entry TTL."""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from . import config


class Cache:
    def __init__(self, path: Path = config.CACHE_DB):
        path.parent.mkdir(parents=True, exist_ok=True)
        # One connection shared by the pipeline's worker threads, serialized by a lock.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT, expires REAL)"
        )

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value, expires FROM cache WHERE key = ?", (key,)
            ).fetchone()
        if row is None or row[1] < time.time():
            return None
        return json.loads(row[0])

    def set(self, key: str, value: Any, ttl: float) -> None:
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO cache VALUES (?, ?, ?)",
                (key, json.dumps(value), time.time() + ttl),
            )
            self.conn.commit()

    def clear(self) -> int:
        with self._lock:
            n = self.conn.execute("DELETE FROM cache").rowcount
            self.conn.commit()
        return n
