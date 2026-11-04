"""FastAPI backend for the web UI. Display-only: all logic lives in `pipeline`/`report`."""

import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import boxmethod, config, pipeline
from ..http import HttpClient
from ..models import Analysis
from ..report import rank, render, slug

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Steam Researcher")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


class TagRunRequest(BaseModel):
    tag: str = Field(min_length=1, max_length=100)
    min_reviews: int = Field(config.MIN_REVIEWS, ge=1)
    lo: float = Field(config.MIN_RATING, ge=0, le=100)
    hi: float = Field(config.MAX_RATING, ge=0, le=100)
    max_games: int = Field(15, ge=1, le=50)
    reviews: int = Field(200, ge=10, le=1000)

    @model_validator(mode="after")
    def _range(self):
        if self.lo > self.hi:
            raise ValueError("lo must be <= hi")
        return self


@dataclass
class Job:
    request: TagRunRequest
    status: str = "running"  # running | done | error
    message: str = "Starting..."
    done: int = 0
    total: int = 0
    result: pipeline.TagResult | None = None
    error: str | None = None


_jobs: dict[str, Job] = {}
_lock = threading.Lock()


def game_json(a: Analysis) -> dict:
    """Everything the frontend needs for one game; no math happens in JS."""
    g = a.game
    box = boxmethod.estimate(g.reviews, g.base_price)
    data = a.model_dump(mode="json")
    data.update(
        store_url=g.store_url,
        reviews=g.reviews,
        rating=g.rating,
        price=g.base_price,
        box=box.model_dump(),
        excluded=a.excluded,
        has_histogram=a.has_histogram,
    )
    return data


def _run(job_id: str) -> None:
    job = _jobs[job_id]
    r = job.request

    def step(message: str, done: int, total: int) -> None:
        with _lock:
            job.message, job.done, job.total = message, done, total

    try:
        result = pipeline.run_tag(HttpClient(), r.tag, r.min_reviews, r.lo, r.hi, r.max_games, r.reviews, step)
        with _lock:
            if result is None:
                job.status, job.error = "error", f"No games found for tag {r.tag!r}. Check the spelling."
            else:
                job.status, job.result = "done", result
    except Exception as e:  # surface any failure to the UI instead of a stuck progress bar
        with _lock:
            job.status, job.error = "error", f"{type(e).__name__}: {e}"


def _job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "Unknown run")
    return job


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.post("/api/tag-runs")
def start_tag_run(req: TagRunRequest) -> dict:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = Job(request=req)
    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    return {"id": job_id}


@app.get("/api/tag-runs/{job_id}")
def tag_run_status(job_id: str) -> dict:
    job = _job(job_id)
    with _lock:
        out = {"status": job.status, "message": job.message, "done": job.done, "total": job.total,
               "error": job.error}
        result = job.result
    if result is not None:
        r = job.request
        out["result"] = {
            "tag": r.tag, "min_reviews": r.min_reviews, "lo": r.lo, "hi": r.hi,
            "n_tag_games": result.n_tag_games,
            "n_candidates": len(result.candidates),
            "not_games": result.not_games,
            "unlisted": result.unlisted,
            "games": [game_json(a) for a in rank(result.analyses)],
        }
    return out


@app.get("/api/tag-runs/{job_id}/report.md")
def tag_run_report(job_id: str) -> PlainTextResponse:
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, "Run not finished")
    r, res = job.request, job.result
    text = render(tag=r.tag, analyses=res.analyses, n_candidates=len(res.candidates),
                  n_tag_games=res.n_tag_games, min_reviews=r.min_reviews, lo=r.lo, hi=r.hi,
                  not_games=res.not_games, unlisted=res.unlisted)
    return PlainTextResponse(text, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="{slug(r.tag)}.md"'})


@app.get("/api/games/{appid}")
def game(appid: int, reviews: int = 300) -> dict:
    a = pipeline.analyze_game(HttpClient(), appid, max(10, min(reviews, 1000)))
    if a is None:
        raise HTTPException(404, f"SteamSpy has no data for AppID {appid}")
    return game_json(a)
