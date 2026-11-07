"""Saved runs: every finished tag search or market ranking, so results survive a restart.

Kept in its own SQLite file under DATA_DIR, apart from the cache, so `mr cache clear` keeps them.
A run is stored as its request params plus the pipeline result (TagResult / MarketsResult) as JSON;
`load` rebuilds the result, so reports and CSVs work for old runs too.

The shortlist (games the user starred, with a note) lives in the same file: a snapshot of each game
as it was when starred, so it outlasts the runs it came from.
"""

import json
import sqlite3
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter

from . import config
from .pipeline import MarketsResult, TagResult
from .report import rank

ADAPTERS = {"tag": TypeAdapter(TagResult), "market": TypeAdapter(MarketsResult)}


def compare_key(tags: list[str], min_reviews: int, lo: float, hi: float, reviews: int | None = None) -> str:
    """Runs with the same tags (any order or case), filters and reviews read per game can be compared:
    a bigger review sample alone moves complaint shares and fixability, so its score changes would mislead."""
    return json.dumps([sorted(t.casefold() for t in tags), min_reviews, lo, hi, reviews, config.SCORE_VERSION])


class RunStore:
    def __init__(self, path: Path | None = None):
        path = path or config.RUNS_DB  # read at call time, so tests can point it elsewhere
        self.path = path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.Lock()

    def _db(self) -> sqlite3.Connection:
        # Opened on first use, so importing the web server or the CLI creates no file.
        if self._conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, created REAL, kind TEXT, label TEXT,"
                " n INTEGER, compare_key TEXT, scores TEXT, params TEXT, result TEXT)"
            )
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS shortlist (appid INTEGER PRIMARY KEY, added REAL, note TEXT, snapshot TEXT)"
            )
        return self._conn

    def save(self, kind: str, label: str, params: dict, result: TagResult | MarketsResult,
             run_id: str | None = None) -> str:
        run_id = run_id or uuid.uuid4().hex
        if kind == "tag":
            ranked = rank(result.analyses)
            n, scores = len(ranked), {a.game.appid: a.opportunity.score for a in ranked}
            key = compare_key(params["tags"], params["min_reviews"], params["lo"], params["hi"], params.get("reviews"))
        else:
            n, scores, key = len(result.rows), {}, None
        data = ADAPTERS[kind].dump_json(result).decode()
        with self._lock:
            db = self._db()
            db.execute("INSERT OR REPLACE INTO runs VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                       (run_id, time.time(), kind, label, n, key, json.dumps(scores), json.dumps(params), data))
            db.commit()
        return run_id

    def update_result(self, run_id: str, result: TagResult | MarketsResult) -> bool:
        """Replace a saved run's result (e.g. a summary was added), keeping its time and comparisons."""
        with self._lock:
            db = self._db()
            row = db.execute("SELECT kind FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None:
                return False
            db.execute("UPDATE runs SET result = ? WHERE id = ?",
                       (ADAPTERS[row[0]].dump_json(result).decode(), run_id))
            db.commit()
        return True

    def list(self, limit: int = 50) -> list[dict]:
        with self._lock:
            rows = self._db().execute(
                "SELECT id, created, kind, label, n FROM runs ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(id=r[0], created=r[1], kind=r[2], label=r[3], n=r[4]) for r in rows]

    def load(self, run_id: str) -> dict[str, Any] | None:
        """{id, created, kind, label, params, result} with the result rebuilt, or None."""
        with self._lock:
            row = self._db().execute(
                "SELECT id, created, kind, label, params, result FROM runs WHERE id = ?", (run_id,)
            ).fetchone()
        if row is None:
            return None
        return dict(id=row[0], created=row[1], kind=row[2], label=row[3], params=json.loads(row[4]),
                    result=ADAPTERS[row[2]].validate_json(row[5]))

    def delete(self, run_id: str) -> bool:
        with self._lock:
            db = self._db()
            n = db.execute("DELETE FROM runs WHERE id = ?", (run_id,)).rowcount
            db.commit()
        return n > 0

    def star(self, appid: int, snapshot: dict) -> None:
        """Add a game to the shortlist, or refresh its snapshot (its note and time stay)."""
        with self._lock:
            db = self._db()
            db.execute("INSERT INTO shortlist VALUES (?, ?, '', ?)"
                       " ON CONFLICT(appid) DO UPDATE SET snapshot = excluded.snapshot",
                       (appid, time.time(), json.dumps(snapshot)))
            db.commit()

    def unstar(self, appid: int) -> bool:
        with self._lock:
            db = self._db()
            n = db.execute("DELETE FROM shortlist WHERE appid = ?", (appid,)).rowcount
            db.commit()
        return n > 0

    def set_note(self, appid: int, note: str) -> bool:
        with self._lock:
            db = self._db()
            n = db.execute("UPDATE shortlist SET note = ? WHERE appid = ?", (note, appid)).rowcount
            db.commit()
        return n > 0

    def shortlist(self) -> "list[dict]":  # quoted: the method list() shadows the builtin here
        """Starred games, newest first: {appid, added, note, **snapshot}."""
        with self._lock:
            rows = self._db().execute(
                "SELECT appid, added, note, snapshot FROM shortlist ORDER BY added DESC").fetchall()
        return [{**json.loads(r[3]), "appid": r[0], "added": r[1], "note": r[2]} for r in rows]

    def previous_scores(self, run_id: str) -> dict[int, float] | None:
        """Scores of the last comparable tag run saved before this one; None if there is none."""
        with self._lock:
            db = self._db()
            row = db.execute("SELECT created, compare_key FROM runs WHERE id = ?", (run_id,)).fetchone()
            if row is None or row[1] is None:
                return None
            prev = db.execute(
                "SELECT scores FROM runs WHERE compare_key = ? AND created < ? ORDER BY created DESC LIMIT 1",
                (row[1], row[0]),
            ).fetchone()
        return {int(k): v for k, v in json.loads(prev[0]).items()} if prev else None


def changes(scores: dict[int, float], previous: dict[int, float] | None) -> dict[int, float | None]:
    """appid -> score change since the previous run, None for a game that is new in the ranking.

    Empty when there is no previous run, so nothing is marked.
    """
    if previous is None:
        return {}
    return {appid: (s - previous[appid] if appid in previous else None) for appid, s in scores.items()}
