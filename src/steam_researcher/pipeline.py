"""Shared steps used by `discover`, `analyze` and `report`."""

from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field

import httpx

from . import config, risk, scoring
from .market import MarketStats, TagMarket, market_stats
from .http import HttpClient, RetryableStatus
from .i18n import _
from .mining import mine
from .discover import filter_candidates
from .models import Analysis, Game, GameSummary, HistPoint, OpportunitySummary, Review
from .notices import BROAD_TAG_GAMES, friendly_error
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


def review_sample(http: HttpClient, appid: int, kind: str, limit: int) -> list[Review]:
    """Half the most helpful reviews of all time, half the newest: helpful reviews are often
    years old, so they alone miss what players say about the game as it is now."""
    helpful = steam_store.reviews(http, appid, kind, limit=limit - limit // 2)
    newest = steam_store.reviews(http, appid, kind, limit=limit // 2, order="recent")
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
    if summary:
        positive, total, with_offtopic = summary
        source, offtopic = "steam", with_offtopic - total
    elif hist and (total := sum(p.total for p in hist)):
        positive, source = sum(p.up for p in hist), "histogram"
    else:
        return game
    return game.model_copy(update={
        "positive": positive, "negative": total - positive,
        "rating_source": source, "steamspy_rating": game.rating, "offtopic_reviews": offtopic,
    })


def analyze_game(http: HttpClient, appid: int, review_limit: int = 300) -> Analysis | None:
    """Everything known about one game: data, risks, mined reviews, opportunity score."""
    game = steamspy.game_details(http, appid)
    if game is None:
        return None
    details = steam_store.app_details(http, appid)
    hist = steam_store.review_histogram(http, appid)
    game = official_reviews(http, game, hist)

    mining, review_error = None, None
    try:
        negative = review_sample(http, appid, "negative", review_limit)
        positive = review_sample(http, appid, "positive", review_limit)
        mining = mine(negative, positive)
    except (RuntimeError, httpx.HTTPError, RetryableStatus) as e:
        # Steam's review API is sometimes very slow; still rank the game on its other data.
        review_error = friendly_error(e).message

    flags = risk.assess(game, details, hist) + (risk.check_scope(mining) if mining else [])
    opportunity = scoring.score(game, flags, mining, risk.rating_without_bombs(hist))
    return Analysis(
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
    """SteamSpy has no games for this tag."""

    def __init__(self, tag: str):
        super().__init__(f"Unknown tag: {tag}")
        self.tag = tag


def tag_label(tags: list[str]) -> str:
    """How a multi-tag search is named in titles, notices and report file names."""
    return " + ".join(tags)


_UNSEARCHABLE = {t.casefold() for t in config.STEAMSPY_UNSEARCHABLE_TAGS}


def _games_for_tag(http: HttpClient, tag: str, on_step: Callable[[str, int, int], None] | None) -> list[Game]:
    """SteamSpy for most tags; Steam's store search for the ones SteamSpy can't search."""
    if tag.strip().casefold() not in _UNSEARCHABLE:
        return steamspy.games_by_tag(http, tag)
    ids = {name.casefold(): i for name, i in steam_store.tag_ids(http).items()}
    tag_id = ids.get(tag.strip().casefold())
    if tag_id is None:
        return []

    def page(done: int, total: int) -> None:
        if on_step:
            on_step(_("Listing games tagged {tag} from the Steam store", tag=tag), done, total)  # done/total: pages

    return steam_search.games_by_tag(http, tag_id, page)


def tag_games(
    http: HttpClient, tags: list[str], on_step: Callable[[str, int, int], None] | None = None
) -> list[Game]:
    """Games that have every one of the tags. Raises UnknownTag for the first tag with no games."""
    per_tag = []
    for tag in tags:
        games = _games_for_tag(http, tag, on_step)
        if not games:
            raise UnknownTag(tag)
        per_tag.append(games)
    shared = set.intersection(*({g.appid for g in games} for games in per_tag))
    return [g for g in per_tag[0] if g.appid in shared]


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


def run_tag(
    http: HttpClient,
    tags: list[str],
    min_reviews: int,
    lo: float,
    hi: float,
    max_games: int,
    review_limit: int,
    on_step: Callable[[str, int, int], None] | None = None,
) -> TagResult:
    """Steps 1-4 for the games that have all `tags`. Raises UnknownTag if SteamSpy doesn't know a tag.

    Games are analyzed in parallel (config.ANALYZE_WORKERS), starting as soon as each one passes
    the store-type check; the shared HttpClient keeps every host within its rate limit.
    on_step(message, done, total) is always called from the calling thread.
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

        def start(g: Game) -> None:
            futures[pool.submit(analyze_game, http, g.appid, review_limit)] = g

        hits, result.not_games, unlisted = verify_games(http, by_demand, max_games, checking, start)
        result.unlisted = [g.name for g in hits if g.appid in unlisted]
        pending, message = set(futures), _("Analyzing games")
        while pending:
            # Wake at least every second, so on_step can show progress and cancel a run even while
            # one of Steam's slow review pages holds up a game.
            finished, pending = wait(pending, timeout=1, return_when=FIRST_COMPLETED)
            if finished:
                message = _("Analyzed {name}", name=futures[next(iter(finished))].name)
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
    failed: list[tuple[str, str]] = field(default_factory=list)  # (tag, friendly reason)
    skipped: list[str] = field(default_factory=list)  # tags SteamSpy can't search (too slow to sweep)


def run_markets(
    http: HttpClient,
    min_reviews: int,
    lo: float,
    hi: float,
    on_step: Callable[[str, int, int], None] | None = None,
) -> MarketsResult:
    """Market stats for every Steam tag SteamSpy can search: one request per tag (~1/s, cached 24 h).

    Tags only Steam's store search can list take minutes each, so they are skipped here.
    """
    names = steam_store.tag_names(http)
    tags = [t for t in names if t.casefold() not in _UNSEARCHABLE]
    result = MarketsResult(rows=[], skipped=[t for t in names if t.casefold() in _UNSEARCHABLE])
    for i, tag in enumerate(tags):
        if on_step:
            on_step(_("Reading tag {tag}", tag=tag), i, len(tags))
        try:
            games = steamspy.games_by_tag(http, tag)
        except Exception as e:  # one broken tag must not sink the whole sweep
            result.failed.append((tag, friendly_error(e).message))
            continue
        if games:
            result.rows.append(TagMarket(tag=tag, stats=market_stats(games, min_reviews, lo, hi)))
    result.rows.sort(key=market_rank)
    return result


def market_rank(row: TagMarket) -> tuple:
    """Specific tags with several underserved games first, by gap. Broad tags (Indie, Action...) have
    the most underserved games only because they are huge, and a tag with 1-2 such games proves little:
    both go last."""
    m = row.stats
    tier = 2 if m.n_underserved < config.MARKET_MIN_UNDERSERVED else 1 if m.n_games > BROAD_TAG_GAMES else 0
    return tier, -m.gap, -m.n_underserved
