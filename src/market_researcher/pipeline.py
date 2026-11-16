"""Shared steps used by `discover`, `analyze` and `report`."""

import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import httpx

from . import backtest, config, risk, scoring
from .market import MIN_TRACK_ENTRANTS, MarketStats, TagMarket, TrackRecord, market_stats, wilson_low
from .http import HttpClient, RetryableStatus
from .i18n import _
from .mining import mine
from .discover import filter_candidates
from .models import Analysis, Game, GameSummary, HistPoint, OpportunitySummary, Review
from .notices import friendly_error
from .sources import steam_search, steam_store, steamspy


def verify_games(
    http: HttpClient,
    candidates: list[Game],
    limit: int,
    progress: Callable[[Game], None] | None = None,
    on_hit: Callable[[Game], None] | None = None,
) -> tuple[list[Game], list[str], set[int]]:
    """'Games Only': SteamSpy has no type field, so confirm with Steam appdetails.

    on_hit(game) is called as soon as a game is kept, so callers can start work on it early.
    Returns (games kept, excluded non-game descriptions, appids with no store page).
    """
    hits, not_games, unlisted = [], [], set()
    for g in candidates:
        if len(hits) >= limit:
            break
        if progress:
            progress(g)
        details = steam_store.app_details(http, g.appid)
        if details is None:
            unlisted.add(g.appid)
        elif details.type != "game":
            not_games.append(f"{g.name} ({details.type})")
            continue
        hits.append(g)
        if on_hit:
            on_hit(g)
    return hits, not_games, unlisted


def review_sample(http: HttpClient, appid: int, kind: str, limit: int,
                  on_page: Callable[[int], None] | None = None) -> list[Review]:
    """Half the most helpful reviews of all time, half the newest: helpful reviews are often
    years old, so they alone miss what players say about the game as it is now.
    on_page(n): reviews fetched so far (of about `limit`)."""
    helpful = steam_store.reviews(http, appid, kind, limit=limit - limit // 2, on_page=on_page)
    first = len(helpful)
    newest = steam_store.reviews(http, appid, kind, limit=limit // 2, order="recent",
                                 on_page=on_page and (lambda n: on_page(first + n)))
    seen = {r.recommendation_id for r in helpful}
    return helpful + [r for r in newest if r.recommendation_id not in seen]


def official_reviews(http: HttpClient, game: Game, hist: list[HistPoint]) -> Game:
    """Steam's own review numbers instead of SteamSpy's estimate (they differ by several points).
    Falls back to the histogram totals, then keeps SteamSpy's."""
    try:
        summary = steam_store.review_summary(http, game.appid)
    except (RuntimeError, httpx.HTTPError, RetryableStatus):
        summary = None
    offtopic = 0
    hist_total = sum(p.total for p in hist) if hist else 0
    # Steam's summary is sometimes far too small: Apex Legends (Nov 2026) got 1,588 reviews from it, while its
    # histogram holds 1.18 million and its store page 453,416 in English alone. Then the histogram is used.
    # Compared with the total including review-bomb periods, which the histogram counts too.
    if summary and summary[2] < hist_total / 2:
        summary = None
    if summary:
        positive, total, with_offtopic = summary
        source, offtopic = "steam", with_offtopic - total
    elif total := hist_total:
        positive, source = sum(p.up for p in hist), "histogram"
    else:
        return game
    return game.model_copy(update={
        "positive": positive, "negative": total - positive,
        "rating_source": source, "steamspy_rating": game.rating, "offtopic_reviews": offtopic,
    })


# progress(stage, done, total) while one game is analyzed: "details" (store data, histogram, review
# numbers), then "reviews" with the review texts fetched so far out of about 2 x review_limit.
Progress = Callable[[str, int, int], None]


def analyze_game(http: HttpClient, appid: int, review_limit: int = 300,
                 progress: Progress | None = None) -> Analysis | None:
    """Everything known about one game: data, risks, mined reviews, opportunity score."""
    say = progress or (lambda stage, done, total: None)
    say("details", 0, 0)
    game = steamspy.game_details(http, appid)
    if game is None:
        return None
    details = steam_store.app_details(http, appid)
    hist = steam_store.review_histogram(http, appid)
    game = official_reviews(http, game, hist)

    mining, review_error = None, None
    fetch_errors = (RuntimeError, httpx.HTTPError, RetryableStatus)
    total = 2 * review_limit
    say("reviews", 0, total)
    try:
        negative = review_sample(http, appid, "negative", review_limit, lambda n: say("reviews", n, total))
    except fetch_errors as e:
        # Steam's review API is sometimes very slow; still rank the game on its other data.
        review_error = friendly_error(e).message
    else:
        try:
            positive = review_sample(http, appid, "positive", review_limit,
                                     lambda n: say("reviews", len(negative) + n, total))
        except fetch_errors:  # complaints and fixability come from the negatives; only "what players love" is lost
            positive = []
        mining = mine(negative, positive)

    flags = risk.assess(game, details, hist) + (risk.check_scope(mining) if mining else [])
    opportunity = scoring.score(game, flags, mining, risk.rating_without_bombs(hist))
    return Analysis(
        analyzed_at=time.time(),
        game=game,
        details=details,
        histogram=hist,
        flags=flags,
        mining=mining,
        review_error=review_error,
        opportunity=opportunity,
    )


class Cancelled(Exception):
    """Raised by an on_step callback to stop a run (the web UI's Cancel button)."""


class UnknownTag(Exception):
    """Steam's tag catalog has no such tag."""

    def __init__(self, tag: str):
        super().__init__(f"Unknown tag: {tag}")
        self.tag = tag


def tag_label(tags: list[str]) -> str:
    """How a multi-tag search is named in titles, notices and report file names."""
    return " + ".join(tags)


# Game panels show SteamSpy's tag names (steamspy.game_details); a click on one searches Steam's name.
_STEAM_NAMES = {spy.casefold(): steam.casefold() for steam, spy in config.STEAMSPY_TAG_NAMES.items()}


def tag_games(
    http: HttpClient, tags: list[str], on_step: Callable[[str, int, int], None] | None = None
) -> list[Game]:
    """Games with every one of the tags and a review score, from Steam's store search in one query.
    Raises UnknownTag for the first tag Steam's catalog doesn't have."""
    ids = {name.casefold(): i for name, i in steam_store.tag_ids(http).items()}
    tag_ids = []
    for tag in tags:
        key = tag.strip().casefold()
        tag_id = ids.get(_STEAM_NAMES.get(key, key))
        if tag_id is None:
            raise UnknownTag(tag)
        tag_ids.append(tag_id)

    def page(done: int, total: int) -> None:
        if on_step:
            on_step(_("Listing games tagged {tag} from the Steam store", tag=tag_label(tags)), done, total)  # pages

    return steam_search.games_by_tags(http, list(dict.fromkeys(tag_ids)), page)


@dataclass
class TagResult:
    n_tag_games: int
    candidates: list[Game]
    analyses: list[Analysis] = field(default_factory=list)
    not_games: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    n_enough_reviews: int = 0  # games with >= min_reviews (explains "0 candidates")
    failed: list[tuple[str, str]] = field(default_factory=list)  # (game name, friendly reason)
    market: MarketStats | None = None  # the whole tag, not just the analyzed games
    summaries: dict[str, OpportunitySummary] = field(default_factory=dict)  # language -> LLM summary (summary.py)
    game_summaries: dict[int, dict[str, GameSummary]] = field(default_factory=dict)  # appid -> language -> summary
    track: TrackRecord | None = None  # the tag's track record, measured on request after the run (track_record)


def run_tag(
    http: HttpClient,
    tags: list[str],
    min_reviews: int,
    lo: float,
    hi: float,
    max_games: int,
    review_limit: int,
    on_step: Callable[[str, int, int], None] | None = None,
    on_game: Callable[[int, str, str, int, int, Analysis | None], None] | None = None,
) -> TagResult:
    """Steps 1-4 for the games that have all `tags`. Raises UnknownTag if Steam doesn't know a tag.

    Games are analyzed in parallel (config.ANALYZE_WORKERS), starting as soon as each one passes
    the store-type check; the shared HttpClient keeps every host within its rate limit.
    on_step(message, done, total) is always called from the calling thread.
    on_game(appid, name, stage, done, total, analysis) follows each game: "store" (its store-type check),
    the stages of analyze_game ("details", "reviews"), then "done" with its Analysis (None if it failed).
    It is called from the worker threads too, so it must be thread-safe.
    """
    games = tag_games(http, tags, on_step)
    candidates = filter_candidates(games, min_reviews, lo, hi)
    result = TagResult(
        n_tag_games=len(games),
        candidates=candidates,
        n_enough_reviews=sum(g.reviews >= min_reviews for g in games),
        market=market_stats(games, min_reviews, lo, hi),
    )
    by_demand = sorted(candidates, key=lambda g: -g.reviews)
    n_check = min(max_games, len(by_demand))

    futures = {}  # future -> game, in the order the games were kept
    pool = ThreadPoolExecutor(max_workers=config.ANALYZE_WORKERS)
    stopped = False
    try:

        def done() -> int:
            return sum(f.done() for f in futures)

        def checking(g: Game) -> None:
            if on_step:
                on_step(_("Checking store type: {name}", name=g.name), done(), n_check)
            if on_game:
                on_game(g.appid, g.name, "store", 0, 0, None)

        def start(g: Game) -> None:
            progress = on_game and (lambda stage, d, n, g=g: on_game(g.appid, g.name, stage, d, n, None))
            futures[pool.submit(analyze_game, http, g.appid, review_limit, progress)] = g

        hits, result.not_games, unlisted = verify_games(http, by_demand, max_games, checking, start)
        result.unlisted = [g.name for g in hits if g.appid in unlisted]
        pending, message = set(futures), _("Analyzing games")
        while pending:
            # Wake at least every second, so on_step can show progress and cancel a run even while
            # one of Steam's slow review pages holds up a game.
            finished, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            if finished:
                message = _("Analyzed {name}", name=futures[next(iter(finished))].name)
            if on_game:
                for f in finished:
                    g = futures[f]
                    on_game(g.appid, g.name, "done", 0, 0, None if f.exception() else f.result())
            if on_step:
                on_step(message, len(futures) - len(pending), len(hits))
    except BaseException:
        stopped = True
        raise
    finally:
        # Cancelled or failed: drop the games not started yet; the few running finish in the background.
        pool.shutdown(wait=not stopped, cancel_futures=stopped)

    for f, g in futures.items():  # keep the deterministic order of `hits`
        try:
            a = f.result()
        except Exception as e:  # one broken game must not sink the whole run
            result.failed.append((g.name, friendly_error(e).message))
            continue
        if a is not None:
            result.analyses.append(a)
    return result


@dataclass
class MarketsResult:
    rows: list[TagMarket]  # most underserved first
    failed: list[tuple[str, str]] = field(default_factory=list)  # (tag, friendly reason); only in old saved runs
    skipped: list[str] = field(default_factory=list)  # tags SteamSpy couldn't search; only in old saved runs


def run_markets(
    http: HttpClient,
    min_reviews: int,
    lo: float,
    hi: float,
    on_step: Callable[[str, int, int], None] | None = None,
) -> MarketsResult:
    """Market stats for every Steam tag from one read of every rated game on Steam's store search (~730 pages,
    ~36 min the first time, then cached a week). A search row carries only a game's first 7 tags, so a tag's
    market counts the games it is a main tag of: fewer than its search finds (docs/measurements.md).
    """
    def page(done: int, total: int) -> None:
        if on_step:
            on_step(_("Reading every rated game from the Steam store"), done, total)

    games = steam_search.games_by_tags(http, [], page)
    by_tag: dict[int, list[Game]] = {}
    for g in games:
        for tag_id in g.tag_ids:
            by_tag.setdefault(tag_id, []).append(g)
    start = backtest.month(int(time.time())) - backtest.HORIZON - backtest.OUTCOME
    result = MarketsResult(rows=[TagMarket(tag=name, stats=market_stats(by_tag[i], min_reviews, lo, hi),
                                           **earlier_hits(by_tag[i], start))
                                 for name, i in steam_store.tag_ids(http).items() if by_tag.get(i)])
    result.rows.sort(key=market_rank)
    return result


def earlier_hits(games: list[Game], start: int) -> dict:
    """{"entrants", "hits"}: the games the store dates in the HORIZON months from `start` (a backtest month), and
    those now at 500+ reviews and 80%+ positive. Estimates track_record's measure without review histories:
    Spearman +0.86 with it across 363 tags (docs/measurements.md)."""
    entrants = [g for g in games if g.release_date
                and start <= g.release_date.year * 12 + g.release_date.month - 1 < start + backtest.HORIZON]
    hits = sum(g.reviews >= backtest.SUCCESS_REVIEWS and g.rating >= backtest.SUCCESS_RATING for g in entrants)
    return {"entrants": len(entrants), "hits": hits}


def market_rank(row: TagMarket) -> tuple:
    """Highest earlier entrants' hit rate first: in the backtest (reports/backtest.md) it was the one market
    measure that predicted how new games did (rho +0.47; top fifth 13.3% hits vs bottom 5.9%), while
    well-served games, market size and the unmet share did not. By the low end of its 95% interval, so a few
    lucky games don't top the list: in the backtest that predicted as well (check rho +0.48 vs +0.47; recent
    +0.46 vs +0.51; docs/measurements.md). Tags with too few entrants to tell go last, biggest market first."""
    if row.entrants < MIN_TRACK_ENTRANTS:
        return 1, 0.0, -row.stats.n_demand
    return 0, -wilson_low(row.hits, row.entrants), -row.entrants


def track_record(http: HttpClient, tags: list[str], on_step: Callable[[str, int, int], None] | None = None,
                 now: float | None = None) -> TrackRecord:
    """The tag's games released 48-24 months ago and how many became hits in their first 24 months, from one
    review histogram per game (cached 30 days). The backtest's definitions, measured at today's month."""
    now = time.time() if now is None else now
    start = backtest.month(int(now)) - backtest.HORIZON - backtest.OUTCOME
    first = start - config.TRACK_RELEASE_MARGIN  # older games can't be entrants (config.TRACK_RELEASE_MARGIN)
    games = [g for g in tag_games(http, tags) if g.positive + g.negative >= backtest.MIN_HIST_REVIEWS
             and not (g.release_date and g.release_date.year * 12 + g.release_date.month - 1 < first)]
    if len(games) > config.TRACK_MAX_GAMES:
        return TrackRecord(start=start, measured_at=now, too_broad=len(games))
    hists = []
    for i, g in enumerate(games):
        if on_step:
            on_step(_("Reading review histories"), i, len(games))
        try:
            hists.append(steam_store.review_histogram(http, g.appid, ttl=backtest.HIST_TTL))
        except Exception:  # one missing history must not sink the measure; that game just isn't counted
            continue
    if on_step:
        on_step(_("Reading review histories"), len(games), len(games))
    out = backtest.outcomes(hists, start, backtest.HORIZON, backtest.OUTCOME)
    return TrackRecord(start=start, months=backtest.HORIZON, entrants=out.entrants, hits=out.hits, sold=out.sold,
                       measured_at=now)
