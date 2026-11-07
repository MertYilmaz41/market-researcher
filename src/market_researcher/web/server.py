"""FastAPI backend for the web UI. Display-only: all logic lives in `pipeline`/`report`/`notices`."""

import contextvars
import hashlib
import threading
import time
import uuid
from dataclasses import dataclass, field
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
from ..report import rank, ranking_csv, rating_source_text, render, shortlist_csv, slug
from ..sources import steam_store

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Market Researcher")
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
    "reviews": N_("Reviews read per game"),
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
    step: int = 0  # counts the steps (listing, checking, analyzing...), so a bar that starts over isn't read as a restart
    # Each game of a tag search as it goes (pipeline.run_tag's on_game), for the live list in the UI:
    # appid -> {name, stage, done, total, score, rating, reviews, moved (when its progress last changed)}.
    games: dict = field(default_factory=dict)
    slow: bool = False  # a review page has taken SLOW_REVIEW_SECONDS: warned once in the status
    result: pipeline.TagResult | pipeline.MarketsResult | None = None
    error: dict | None = None  # a Notice dict


_jobs: dict[str, Job] = {}
_runs = runs.RunStore()
_lock = threading.Lock()
_summary_lock = threading.Lock()  # one summary at a time: the local model has one GPU
_http_client: HttpClient | None = None
_http_lock = threading.Lock()


def _http() -> HttpClient:
    """One client for the whole server, made on first use. Each HttpClient keeps its own per-host rate
    limit, so separate clients for a search and a lookup running together hit Steam twice as fast (429s)."""
    global _http_client
    with _http_lock:
        if _http_client is None:
            _http_client = HttpClient()
        return _http_client


def game_json(a: Analysis) -> dict:
    """Everything the frontend needs for one game; no math happens in JS."""
    g = a.game
    box = boxmethod.estimate(g.reviews, g.base_price)
    recent, total, _age = risk.recent_activity(a.histogram, a.analyzed_at)
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
        recent_rating=risk.recent_rating(a.histogram, a.analyzed_at),
        score_explained=scoring.explain(a),
        verdict=scoring.verdict(a.opportunity.score),
        why=scoring.why(a),
        checks=risk.checks(a),
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
                job.step += 1
            job.message, job.done, job.total = message, done, total

    def game(appid: int, name: str, stage: str, done: int, total: int, a: Analysis | None) -> None:
        # Called from the pipeline's worker threads too.
        with _lock:
            if stage == "store":  # the game checked before this one either started or wasn't a game
                for k in [k for k, v in job.games.items() if v["stage"] == "store"]:
                    del job.games[k]
            g = job.games.setdefault(appid, {"name": name, "score": None, "rating": None, "reviews": None})
            if stage == "done" and a is not None:
                g.update(score=a.opportunity.score, rating=a.game.rating, reviews=a.game.reviews)
            elif stage == "done":
                stage = "failed"
            g.update(stage=stage, done=done, total=total, moved=_now())

    def finish(**fields) -> None:
        with _lock:
            if job.status != "cancelled":  # a cancelled run ends quietly, whatever it was doing
                for k, v in fields.items():
                    setattr(job, k, v)

    try:
        http = _http()
        if job.kind == "market":
            result = pipeline.run_markets(http, r.min_reviews, r.lo, r.hi, step)
        else:
            result = pipeline.run_tag(http, r.tags, r.min_reviews, r.lo, r.hi, r.max_games, r.reviews, step, game)
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
        return {"tags": steam_store.tag_names(_http())}
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
SLOW_REVIEW_SECONDS = 30  # a game waiting this long for its next review page: Steam's review service is slow


def eta(done: int, total: int, done0: int, since: float, now: float) -> float | None:
    """Seconds left in the current step, at its pace so far. None until there is a pace to go on
    (one item done and a few seconds passed): cached runs finish before an estimate would help."""
    if not total or done >= total or done - done0 < 1 or now - since < 3:
        return None
    return round((now - since) / (done - done0) * (total - done))


def _status(job_id: str, job: Job, result_json) -> dict:
    with _lock:
        running = job.status == "running"
        out = {"status": job.status, "message": job.message, "done": job.done, "total": job.total, "step": job.step,
               "eta": eta(job.done, job.total, job.step_done, job.step_start, _now()) if running else None,
               "error": job.error}
        if job.kind == "tag" and running:
            now = _now()
            out["games"] = [{"appid": k, **{f: v[f] for f in ("name", "stage", "done", "total", "score", "rating", "reviews")}}
                            for k, v in job.games.items()]
            stuck = any(v["stage"] == "reviews" and now - v["moved"] >= SLOW_REVIEW_SECONDS for v in job.games.values())
            if stuck and not job.slow:
                job.slow = True
                out["slow"] = notices.slow_reviews().model_dump()
        result = job.result
    if result is not None:
        out["result"] = result_json(job_id, job.request, result)
    return out


def _score_changes(job_id: str, ranked: list[Analysis]) -> dict[int, float | None]:
    return runs.changes({a.game.appid: a.opportunity.score for a in ranked}, _runs.previous_scores(job_id))


class ShortlistPut(BaseModel):
    run_id: str | None = None  # star the game as it is in this run
    note: Annotated[str, Field(max_length=2000)] | None = None


# Games analyzed by AppID (the "One game" form), so they can be starred too. The latest few only.
_single: dict[int, Analysis] = {}
SINGLE_KEEP = 50


def _remember_single(a: Analysis) -> None:
    with _lock:
        _single.pop(a.game.appid, None)
        _single[a.game.appid] = a
        while len(_single) > SINGLE_KEEP:
            _single.pop(next(iter(_single)))


def _snapshot_of(a: Analysis, source: str, run_id: str | None) -> dict:
    """What the shortlist keeps of a game: how it looked when starred (English labels)."""
    top = a.mining.categories[0] if a.mining and a.mining.categories else None
    return {"name": a.game.name, "score": a.opportunity.score, "rating": a.game.rating, "reviews": a.game.reviews,
            "complaint": top.label if top else "", "complaint_share": top.share if top else None,
            "store_url": a.game.store_url, "source": source, "run_id": run_id}


def _snapshot(job_id: str, appid: int) -> dict:
    job = _job(job_id)
    if job.result is None:
        raise HTTPException(409, _("The run hasn't finished yet."))
    a = next((x for x in job.result.analyses if x.game.appid == appid), None)
    if a is None:
        raise HTTPException(404, _("This game isn't part of the run."))
    return _snapshot_of(a, pipeline.tag_label(job.request.tags), job_id)


def _shortlist_json() -> list[dict]:
    return [{**g, "complaint": _(g["complaint"]) if g["complaint"] else ""} for g in _runs.shortlist()]


@app.get("/api/shortlist")
def get_shortlist() -> dict:
    return {"games": _shortlist_json()}


@app.put("/api/shortlist/{appid}")
def put_shortlist(appid: int, body: ShortlistPut) -> dict:
    """Star a game of a run, and/or change its note. Without either: star a game analyzed by AppID."""
    if body.run_id is not None:
        _runs.star(appid, _snapshot(body.run_id, appid))
    elif body.note is None:
        with _lock:
            a = _single.get(appid)
        if a is None:
            raise HTTPException(404, _("Analyze this game again to star it."))
        _runs.star(appid, _snapshot_of(a, "AppID", None))
    if body.note is not None and not _runs.set_note(appid, body.note.strip()):
        raise HTTPException(404, _("This game isn't on the shortlist."))
    return {"games": _shortlist_json()}


@app.delete("/api/shortlist/{appid}")
def delete_shortlist(appid: int) -> dict:
    if not _runs.unstar(appid):
        raise HTTPException(404, _("This game isn't on the shortlist."))
    return {"games": _shortlist_json()}


@app.get("/api/shortlist.csv")
def shortlist_download() -> PlainTextResponse:
    return PlainTextResponse(shortlist_csv(_runs.shortlist()), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="shortlist.csv"'})


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
        # The map's axes in the score's own units: demand is log10(reviews) from DEMAND_LOG_MIN (0) to
        # DEMAND_LOG_MAX (1); dissatisfaction is MAX_RATING (0) down to MIN_RATING (1) % positive.
        "axes": {"demand_log": [config.DEMAND_LOG_MIN, config.DEMAND_LOG_MAX],
                 "rating": [config.MAX_RATING, config.MIN_RATING]},
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
                negative = pipeline.review_sample(_http(), appid, "negative", job.request.reviews)
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
        a = pipeline.analyze_game(_http(), appid, max(10, min(reviews, 1000)))
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
    _remember_single(a)
    data = game_json(a)
    data["notices"] = [n.model_dump() for n in notices.for_game(a)]
    return data
