"""Tiny SQLite key/value cache with per-entry TTL."""

import json
import sqlite3
import threading
import time
import zlib
from pathlib import Path
from typing import Any

from . import config


class Cache:
    def __init__(self, path: Path | None = None):
        path = path or config.CACHE_DB  # read at call time, so tests can point it elsewhere
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        # One connection shared by the pipeline's worker threads, serialized by a lock.
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.Lock()
        try:  # WAL: a write commits without rewriting the journal, and readers don't block writers
            self.conn.execute("PRAGMA journal_mode=WAL")
        except sqlite3.OperationalError:  # another process holds a lock: keep the current mode
            pass
        # zlib-compressed JSON. Not in the table "cache" that versions before compression use: those
        # versions share this file (an installed copy next to a dev checkout) and would fail on a compressed row.
        self.conn.execute(
            "CREATE TABLE IF NOT EXISTS responses (key TEXT PRIMARY KEY, value BLOB, expires REAL)"
        )

    def get(self, key: str) -> Any | None:
        with self._lock:
            row = self.conn.execute(
                "SELECT value, expires FROM responses WHERE key = ?", (key,)
            ).fetchone()
        if row is None or row[1] < time.time():
            return None
        return json.loads(zlib.decompress(row[0]))

    def set(self, key: str, value: Any, ttl: float) -> None:
        # outside the lock: a big tag list takes a while to serialize. Compressed: Steam's answers are
        # mostly review text, which zlib shrinks several times.
        text = zlib.compress(json.dumps(value).encode(), 6)
        with self._lock:
            self.conn.execute(
                "INSERT OR REPLACE INTO responses VALUES (?, ?, ?)",
                (key, text, time.time() + ttl),
            )
            self.conn.commit()

    def prune(self) -> int:
        """Delete expired entries (nothing else ever does), then give the space back to the disk."""
        with self._lock:
            n = self.conn.execute("DELETE FROM responses WHERE expires < ?", (time.time(),)).rowcount
            self.conn.commit()
            self._shrink()
        return n

    def _shrink(self) -> None:
        """Give freed space back to the disk (call with the lock held). The plain table of versions before
        compression goes too; such a version makes it again when it next opens the cache."""
        self.conn.execute("DROP TABLE IF EXISTS cache")
        self.conn.commit()
        self.conn.execute("VACUUM")
        self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # in WAL mode VACUUM lands in the WAL first

    def stats(self) -> dict:
        """Bytes on disk and how many entries have expired (what prune would delete)."""
        with self._lock:
            expired = self.conn.execute("SELECT COUNT(*) FROM responses WHERE expires < ?", (time.time(),)).fetchone()[0]
        return {"bytes": self.size(), "expired": expired}

    def size(self) -> int:
        """Bytes on disk, the WAL file included."""
        return sum(f.stat().st_size for f in (self.path, self.path.with_name(self.path.name + "-wal")) if f.exists())

    def clear(self) -> int:
        with self._lock:
            n = self.conn.execute("DELETE FROM responses").rowcount
            self.conn.commit()
            self._shrink()
        return n
