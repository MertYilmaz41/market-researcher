"""FastAPI backend for the web UI. Display-only: all logic lives in `pipeline`/`report`/`notices`."""

import threading
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import boxmethod, config, notices, pipeline
from ..http import HttpClient
from ..models import Analysis
from ..report import rank, render, slug
from ..sources import steam_store

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Steam Researcher")
app.mount("/static", StaticFiles(directory=STATIC), name="static")

FIELD_LABELS = {
    "tags": "Steam tags",
    "min_reviews": "Minimum reviews",
    "lo": "% positive from",
    "hi": "% positive to",
    "max_games": "Games to analyze",
    "reviews": "Reviews mined per game",
}


class TagRunRequest(BaseModel):
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(min_length=1, max_length=config.MAX_TAGS)
    min_reviews: int = Field(config.MIN_REVIEWS, ge=1)
    lo: float = Field(config.MIN_RATING, ge=0, le=100)
    hi: float = Field(config.MAX_RATING, ge=0, le=100)
    max_games: int = Field(15, ge=1, le=50)
    reviews: int = Field(200, ge=10, le=1000)

    @model_validator(mode="after")
    def _range(self):
        if self.lo > self.hi:
            raise ValueError("'% positive from' must not be higher than '% positive to'")
        return self


@app.exception_handler(RequestValidationError)
async def _readable_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn pydantic's error list into one sentence a user understands."""
    parts = []
    for err in exc.errors():
        field = next((FIELD_LABELS[p] for p in reversed(err.get("loc", ())) if p in FIELD_LABELS), None)
        msg = err.get("msg", "invalid value").removeprefix("Value error, ")
        parts.append(f"{field}: {msg}" if field else msg)
    notice = notices.Notice(level="error", title="Check the filters", message="; ".join(parts),
                            hint="Fix the highlighted values and try again.")
    return JSONResponse(status_code=422, content={"detail": notice.message, "notice": notice.model_dump()})


@dataclass
class Job:
    request: TagRunRequest
    status: str = "running"  # running | done | error
    message: str = "Starting..."
    done: int = 0
    total: int = 0
    result: pipeline.TagResult | None = None
    error: dict | None = None  # a Notice dict


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
        http = HttpClient()
        result = pipeline.run_tag(http, r.tags, r.min_reviews, r.lo, r.hi, r.max_games, r.reviews, step)
        with _lock:
            job.status, job.result = "done", result
    except pipeline.UnknownTag as e:
        error = notices.unknown_tag(e.tag, notices.known_tags(http)).model_dump()
        with _lock:
            job.status, job.error = "error", error
    except Exception as e:  # surface any failure to the UI instead of a stuck progress bar
        with _lock:
            job.status, job.error = "error", notices.friendly_error(e).model_dump()


def _job(job_id: str) -> Job:
    job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "This run no longer exists (the server was probably restarted).")
    return job


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC / "index.html")


@app.get("/api/tags")
def tags():
    try:
        return {"tags": steam_store.tag_names(HttpClient())}
    except Exception as e:
        notice = notices.friendly_error(e)
        return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})


@app.post("/api/tag-runs")
def start_tag_run(req: TagRunRequest) -> dict:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = Job(request=req)
    threading.Thread(target=_run, args=(job_id,), daemon=True).start()
    pre = notices.for_filters(req.min_reviews, req.lo, req.hi, req.max_games, req.reviews)
    return {"id": job_id, "notices": [n.model_dump() for n in pre]}


@app.get("/api/tag-runs/{job_id}")
def tag_run_status(job_id: str) -> dict:
    job = _job(job_id)
    with _lock:
        out = {"status": job.status, "message": job.message, "done": job.done, "total": job.total,
               "error": job.error}
        result = job.result
    if result is not None:
        r = job.request
        label = pipeline.tag_label(r.tags)
        post = notices.for_tag_result(label, r.min_reviews, r.lo, r.hi, r.max_games, result)
        out["result"] = {
            "tag": label, "tags": r.tags, "min_reviews": r.min_reviews, "lo": r.lo, "hi": r.hi,
            "n_tag_games": result.n_tag_games,
            "n_candidates": len(result.candidates),
            "not_games": result.not_games,
            "unlisted": result.unlisted,
            "games": [game_json(a) for a in rank(result.analyses)],
            "notices": [n.model_dump() for n in post],
        }
    return out


@app.get("/api/tag-runs/{job_id}/report.md")
def tag_run_report(job_id: str) -> PlainTextResponse:
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, "The run hasn't finished yet.")
    r, res = job.request, job.result
    label = pipeline.tag_label(r.tags)
    text = render(tag=label, analyses=res.analyses, n_candidates=len(res.candidates),
                  n_tag_games=res.n_tag_games, min_reviews=r.min_reviews, lo=r.lo, hi=r.hi,
                  not_games=res.not_games, unlisted=res.unlisted)
    return PlainTextResponse(text, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="{slug(label)}.md"'})


@app.get("/api/games/{appid}")
def game(appid: int, reviews: int = 300):
    if appid <= 0:
        raise HTTPException(422, "AppID must be a positive number.")
    try:
        a = pipeline.analyze_game(HttpClient(), appid, max(10, min(reviews, 1000)))
    except Exception as e:
        notice = notices.friendly_error(e)
        return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})
    if a is None:
        notice = notices.Notice(
            level="error", title="Game not found",
            message=f"SteamSpy has no data for AppID {appid}.",
            hint="Check the number on the game's Steam store page (store.steampowered.com/app/<AppID>/). "
                 "Unreleased or very new games may not be listed yet.",
        )
        return JSONResponse(status_code=404, content={"detail": notice.message, "notice": notice.model_dump()})
    data = game_json(a)
    data["notices"] = [n.model_dump() for n in notices.for_game(a)]
    return data
