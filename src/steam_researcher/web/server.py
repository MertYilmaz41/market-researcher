"""FastAPI backend for the web UI. Display-only: all logic lives in `pipeline`/`report`/`notices`."""

import contextvars
import hashlib
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, model_validator

from .. import boxmethod, config, market, notices, pipeline, risk, runs, scoring, summary
from ..http import HttpClient
from ..i18n import LANGS, N_, _, lang, use
from ..mining import llm
from ..models import Analysis
from ..report import rank, ranking_csv, rating_source_text, render, slug
from ..sources import steam_store

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Steam Researcher")
app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.middleware("http")
async def _revalidate_page_files(request: Request, call_next):
    """Browsers must check the page and its scripts on every load (cheap: ETag/304). Without this they
    may reuse an old cached app.js with a newer index.html, which breaks the page after an update."""
    response = await call_next(request)
    if request.url.path == "/" or request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

@app.middleware("http")
async def _language(request: Request, call_next):
    """The interface language for this request: the page sends X-Lang; download links use ?lang=."""
    lang = request.query_params.get("lang") or request.headers.get("x-lang") or "en"
    with use(lang if lang in LANGS else "en"):
        return await call_next(request)


FIELD_LABELS = {
    "tags": N_("Steam tags"),
    "min_reviews": N_("Minimum reviews"),
    "lo": N_("% positive from"),
    "hi": N_("% positive to"),
    "max_games": N_("Games to analyze"),
    "reviews": N_("Reviews mined per game"),
}


class MarketRunRequest(BaseModel):
    min_reviews: int = Field(config.MIN_REVIEWS, ge=1)
    lo: float = Field(config.MIN_RATING, ge=0, le=100)
    hi: float = Field(config.MAX_RATING, ge=0, le=100)

    @model_validator(mode="after")
    def _range(self):
        if self.lo > self.hi:
            raise ValueError(N_("'% positive from' must not be higher than '% positive to'"))
        return self


class TagRunRequest(MarketRunRequest):
    tags: list[Annotated[str, Field(min_length=1, max_length=100)]] = Field(min_length=1, max_length=config.MAX_TAGS)
    max_games: int = Field(15, ge=1, le=50)
    reviews: int = Field(200, ge=10, le=1000)


@app.exception_handler(RequestValidationError)
async def _readable_validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Turn pydantic's error list into one sentence a user understands."""
    parts = []
    for err in exc.errors():
        field = next((_(FIELD_LABELS[p]) for p in reversed(err.get("loc", ())) if p in FIELD_LABELS), None)
        msg = _(err.get("msg", "invalid value").removeprefix("Value error, "))  # pydantic's own stay English
        parts.append(f"{field}: {msg}" if field else msg)
    notice = notices.Notice(level="error", title=_("Check the filters"), message="; ".join(parts),
                            hint=_("Fix the highlighted values and try again."))
    return JSONResponse(status_code=422, content={"detail": notice.message, "notice": notice.model_dump()})


@dataclass
class Job:
    kind: str  # "tag" | "market"
    request: TagRunRequest | MarketRunRequest
    status: str = "running"  # running | done | error | cancelled
    message: str = N_("Starting...")  # translated when it is set (the job runs in its starter's language)
    done: int = 0
    total: int = 0
    step_start: float = 0.0  # when the current step began (monotonic), and its done count then
    step_done: int = 0
    result: pipeline.TagResult | pipeline.MarketsResult | None = None
    error: dict | None = None  # a Notice dict


_jobs: dict[str, Job] = {}
_runs = runs.RunStore()
_lock = threading.Lock()
_summary_lock = threading.Lock()  # one summary at a time: the local model has one GPU


def game_json(a: Analysis) -> dict:
    """Everything the frontend needs for one game; no math happens in JS."""
    g = a.game
    box = boxmethod.estimate(g.reviews, g.base_price)
    recent, total, _age = risk.recent_activity(a.histogram)
    data = a.model_dump(mode="json")
    # Text in the request's language: flag messages, complaint names, design pillars, trends.
    for flag, out in zip(a.flags, data["flags"]):
        out["message"] = flag.text()
        out["label"] = _(config.RISK_LABELS.get(flag.code, flag.code))
    for c in (data.get("mining") or {}).get("categories", []):
        c["trend_kind"] = "still" if c["trend"].startswith("still") else ("fading" if c["trend"] else "")
        c["label"], c["pillar"] = _(c["label"]), _(c["pillar"])
        c["trend"] = _(c["trend"]) if c["trend"] else ""
    data.update(
        store_url=g.store_url,
        reviews=g.reviews,
        rating=g.rating,
        rating_source_text=rating_source_text(g),
        price=g.base_price,
        box=box.model_dump(),
        excluded=a.excluded,
        has_histogram=a.has_histogram,
        recent_reviews=recent,
        recent_share=recent / total if total else None,
        recent_rating=risk.recent_rating(a.histogram),
        score_explained=scoring.explain(a),
    )
    return data


def _run(job_id: str) -> None:
    job = _jobs[job_id]
    r = job.request

    def step(message: str, done: int, total: int) -> None:
        with _lock:
            if job.status == "cancelled":  # the pipeline calls this often: stop at the next step
                raise pipeline.Cancelled
            if total != job.total or done < job.done:  # a new step (listing, checking, analyzing...)
                job.step_start, job.step_done = _now(), done
            job.message, job.done, job.total = message, done, total

    def finish(**fields) -> None:
        with _lock:
            if job.status != "cancelled":  # a cancelled run ends quietly, whatever it was doing
                for k, v in fields.items():
                    setattr(job, k, v)

    try:
        http = HttpClient()
        if job.kind == "market":
            result = pipeline.run_markets(http, r.min_reviews, r.lo, r.hi, step)
        else:
            result = pipeline.run_tag(http, r.tags, r.min_reviews, r.lo, r.hi, r.max_games, r.reviews, step)
        if job.status == "cancelled":
            return
        # Saved before it shows as done, so the first result the UI sees can already compare.
        label = pipeline.tag_label(r.tags) if job.kind == "tag" else "All tags"
        _runs.save(job.kind, label, r.model_dump(), result, run_id=job_id)
        finish(status="done", result=result)
    except pipeline.Cancelled:
        pass
    except pipeline.UnknownTag as e:
        finish(status="error", error=notices.unknown_tag(e.tag, notices.known_tags(http)).model_dump())
    except Exception as e:  # surface any failure to the UI instead of a stuck progress bar
        finish(status="error", error=notices.friendly_error(e).model_dump())


REQUESTS = {"tag": TagRunRequest, "market": MarketRunRequest}


def _job(job_id: str, kind: str = "tag") -> Job:
    """A running job, or a finished one from the saved runs."""
    job = _jobs.get(job_id)
    if job is None:
        saved = _runs.load(job_id)
        if saved is not None:
            job = Job(kind=saved["kind"], request=REQUESTS[saved["kind"]](**saved["params"]),
                      status="done", message="", result=saved["result"])
            with _lock:
                _jobs[job_id] = job
    if job is None or job.kind != kind:
        raise HTTPException(404, _("This run no longer exists. It may have been deleted, or the server "
                                   "was restarted while it was running."))
    return job


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
    return HTMLResponse(versioned_index())


def versioned_index() -> str:
    """index.html with every local script and stylesheet URL tagged ?v=<hash of the static files>.

    After an update the URLs differ, so a browser can't keep running an old cached app.js next to the
    new page (that left the search button stuck on "Searching..."). Module imports such as
    "/static/palette.js" are versioned through the page's import map.
    """
    files = sorted(STATIC.glob("*.*"))
    v = hashlib.sha256(b"".join(f.name.encode() + f.read_bytes() for f in files)).hexdigest()[:12]
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    html = html.replace('href="/static/style.css"', f'href="/static/style.css?v={v}"')
    html = html.replace('src="/static/app.js"', f'src="/static/app.js?v={v}"')
    scripts = "".join(f'\n        "/static/{f.name}": "/static/{f.name}?v={v}",' for f in files if f.suffix == ".js")
    return html.replace('"imports": {', '"imports": {' + scripts, 1)


@app.get("/api/tags")
def tags():
    try:
        return {"tags": steam_store.tag_names(HttpClient())}
    except Exception as e:
        notice = notices.friendly_error(e)
        return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})


def _start(kind: str, req: TagRunRequest | MarketRunRequest) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = Job(kind=kind, request=req, message=_(Job.message))
    # The job runs in the language of the request that started it (progress messages, errors).
    threading.Thread(target=contextvars.copy_context().run, args=(_run, job_id), daemon=True).start()
    return job_id


_now = time.monotonic  # the clock for time estimates (tests set it)


def eta(done: int, total: int, done0: int, since: float, now: float) -> float | None:
    """Seconds left in the current step, at its pace so far. None until there is a pace to go on
    (one item done and a few seconds passed): cached runs finish before an estimate would help."""
    if not total or done >= total or done - done0 < 1 or now - since < 3:
        return None
    return round((now - since) / (done - done0) * (total - done))


def _status(job_id: str, job: Job, result_json) -> dict:
    with _lock:
        running = job.status == "running"
        out = {"status": job.status, "message": job.message, "done": job.done, "total": job.total,
               "eta": eta(job.done, job.total, job.step_done, job.step_start, _now()) if running else None,
               "error": job.error}
        result = job.result
    if result is not None:
        out["result"] = result_json(job_id, job.request, result)
    return out


def _score_changes(job_id: str, ranked: list[Analysis]) -> dict[int, float | None]:
    return runs.changes({a.game.appid: a.opportunity.score for a in ranked}, _runs.previous_scores(job_id))


def tag_result_json(job_id: str, r: TagRunRequest, result: pipeline.TagResult) -> dict:
    label = pipeline.tag_label(r.tags)
    post = notices.for_tag_result(label, r.min_reviews, r.lo, r.hi, r.max_games, result)
    ranked = rank(result.analyses)
    changes = _score_changes(job_id, ranked)
    games = []
    for a in ranked:
        g = game_json(a)
        g["summary"] = _summary_json(result.game_summaries.get(a.game.appid, {}).get(lang()))
        if a.game.appid in changes:  # only when an earlier run with the same tags and filters exists
            g["score_change"] = changes[a.game.appid]
            g["new"] = changes[a.game.appid] is None
        games.append(g)
    return {
        "tag": label, "tags": r.tags, "min_reviews": r.min_reviews, "lo": r.lo, "hi": r.hi,
        "n_tag_games": result.n_tag_games,
        "n_candidates": len(result.candidates),
        "not_games": result.not_games,
        "unlisted": result.unlisted,
        "market": result.market.model_dump() if result.market else None,
        "well_served": config.WELL_SERVED_RATING,
        "games": games,
        "summary": _summary_json(result.summaries.get(lang())),
        "llm_model": config.LLM_MODEL,
        "compared": bool(changes),
        "notices": [n.model_dump() for n in post],
    }


def _summary_json(s) -> dict | None:
    return s.model_dump() if s is not None else None


def market_result_json(job_id: str, r: MarketRunRequest, result: pipeline.MarketsResult) -> dict:
    return {
        "min_reviews": r.min_reviews, "lo": r.lo, "hi": r.hi,
        "well_served": config.WELL_SERVED_RATING,
        "rows": [{"tag": row.tag, **row.stats.model_dump()} for row in result.rows],
        "skipped": result.skipped,
        "failed": [{"tag": t, "reason": why} for t, why in result.failed],
    }


@app.post("/api/tag-runs")
def start_tag_run(req: TagRunRequest) -> dict:
    job_id = _start("tag", req)
    pre = notices.for_filters(req.min_reviews, req.lo, req.hi, req.max_games, req.reviews)
    return {"id": job_id, "notices": [n.model_dump() for n in pre]}


@app.get("/api/tag-runs/{job_id}")
def tag_run_status(job_id: str) -> dict:
    return _status(job_id, _job(job_id), tag_result_json)


@app.post("/api/market-runs")
def start_market_run(req: MarketRunRequest) -> dict:
    pre = notices.for_filters(req.min_reviews, req.lo, req.hi, 0, 0)
    return {"id": _start("market", req), "notices": [n.model_dump() for n in pre]}


@app.get("/api/market-runs/{job_id}")
def market_run_status(job_id: str) -> dict:
    return _status(job_id, _job(job_id, "market"), market_result_json)


def _cancel(job: Job) -> dict:
    """Stops a running job at its next step; the UI is free at once. A finished job is left as is."""
    with _lock:
        if job.status == "running":
            job.status, job.message = "cancelled", _("Cancelled")
        return {"status": job.status}


@app.post("/api/tag-runs/{job_id}/cancel")
def cancel_tag_run(job_id: str) -> dict:
    return _cancel(_job(job_id))


@app.post("/api/market-runs/{job_id}/cancel")
def cancel_market_run(job_id: str) -> dict:
    return _cancel(_job(job_id, "market"))


@app.get("/api/runs")
def list_runs() -> dict:
    return {"runs": _runs.list()}


@app.delete("/api/runs/{run_id}")
def delete_run(run_id: str) -> dict:
    if not _runs.delete(run_id):
        raise HTTPException(404, _("This run doesn't exist."))
    with _lock:
        _jobs.pop(run_id, None)
    return {"deleted": run_id}


@app.get("/api/tag-runs/{job_id}/ranking.csv")
def tag_run_csv(job_id: str) -> PlainTextResponse:
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, _("The run hasn't finished yet."))
    ranked = rank(job.result.analyses)
    text = ranking_csv(ranked, _score_changes(job_id, ranked))
    return PlainTextResponse(text, media_type="text/csv", headers={
        "Content-Disposition": f'attachment; filename="{slug(pipeline.tag_label(job.request.tags))}.csv"'})


@app.get("/api/tag-runs/{job_id}/report.md")
def tag_run_report(job_id: str) -> PlainTextResponse:
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, _("The run hasn't finished yet."))
    r, res = job.request, job.result
    label = pipeline.tag_label(r.tags)
    text = render(tag=label, analyses=res.analyses, n_candidates=len(res.candidates),
                  n_tag_games=res.n_tag_games, min_reviews=r.min_reviews, lo=r.lo, hi=r.hi,
                  not_games=res.not_games, unlisted=res.unlisted,
                  market=market.summary(res.market) if res.market else "",
                  summary=res.summaries.get(lang()),
                  game_summaries={k: v[lang()] for k, v in res.game_summaries.items() if lang() in v})
    return PlainTextResponse(text, media_type="text/markdown", headers={
        "Content-Disposition": f'attachment; filename="{slug(label)}.md"'})


@app.post("/api/tag-runs/{job_id}/summary")
def write_summary(job_id: str):
    """The run's opportunity summary in the request's language, written by the local LLM once and saved."""
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, _("The run hasn't finished yet."))
    res, language = job.result, lang()
    with _summary_lock:
        s = res.summaries.get(language)
        if s is None:
            try:
                s = summary.write(pipeline.tag_label(job.request.tags), res.analyses, res.market, language)
            except llm.LLMUnavailable as e:
                notice = notices.llm_unavailable(e.missing_model)
                return JSONResponse(status_code=503, content={"detail": notice.message, "notice": notice.model_dump()})
            except Exception as e:
                notice = notices.friendly_error(e)
                return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})
            res.summaries[language] = s
            _runs.update_result(job_id, res)
    return {"summary": _summary_json(s)}


@app.post("/api/tag-runs/{job_id}/games/{appid}/summary")
def write_game_summary(job_id: str, appid: int):
    """One game of the run, read by the local LLM (why players are unhappy, what to do, complaints no
    category covers), in the request's language; written once and saved with the run."""
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, _("The run hasn't finished yet."))
    res, language = job.result, lang()
    a = next((x for x in res.analyses if x.game.appid == appid), None)
    if a is None:
        raise HTTPException(404, _("This game isn't part of the run."))
    with _summary_lock:
        s = res.game_summaries.get(appid, {}).get(language)
        if s is None:
            try:
                negative = pipeline.review_sample(HttpClient(), appid, "negative", job.request.reviews)
                s = summary.write_game(a, negative, language)
            except llm.LLMUnavailable as e:
                notice = notices.llm_unavailable(e.missing_model)
                return JSONResponse(status_code=503, content={"detail": notice.message, "notice": notice.model_dump()})
            except Exception as e:
                notice = notices.friendly_error(e)
                return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})
            res.game_summaries.setdefault(appid, {})[language] = s
            _runs.update_result(job_id, res)
    return {"summary": _summary_json(s)}


@app.get("/api/games/{appid}")
def game(appid: int, reviews: int = 300):
    if appid <= 0:
        raise HTTPException(422, _("AppID must be a positive number."))
    try:
        a = pipeline.analyze_game(HttpClient(), appid, max(10, min(reviews, 1000)))
    except Exception as e:
        notice = notices.friendly_error(e)
        return JSONResponse(status_code=502, content={"detail": notice.message, "notice": notice.model_dump()})
    if a is None:
        notice = notices.Notice(
            level="error", title=_("Game not found"),
            message=_("SteamSpy has no data for AppID {appid}.", appid=appid),
            hint=_("Check the number on the game's Steam store page (store.steampowered.com/app/<AppID>/). "
                   "Unreleased or very new games may not be listed yet."),
        )
        return JSONResponse(status_code=404, content={"detail": notice.message, "notice": notice.model_dump()})
    data = game_json(a)
    data["notices"] = [n.model_dump() for n in notices.for_game(a)]
    return data
