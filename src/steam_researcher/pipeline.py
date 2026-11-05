"""Shared steps used by `discover`, `analyze` and `report`."""

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

import httpx

from . import config, risk, scoring
from .http import HttpClient, RetryableStatus
from .mining import mine
from .discover import filter_candidates
from .models import Analysis, Game
from .notices import friendly_error
from .sources import steam_store, steamspy


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


def analyze_game(http: HttpClient, appid: int, review_limit: int = 300) -> Analysis | None:
    """Everything known about one game: data, risks, mined reviews, opportunity score."""
    game = steamspy.game_details(http, appid)
    if game is None:
        return None
    details = steam_store.app_details(http, appid)
    hist = steam_store.review_histogram(http, appid)

    mining, review_error = None, None
    try:
        negative = steam_store.reviews(http, appid, "negative", limit=review_limit)
        positive = steam_store.reviews(http, appid, "positive", limit=review_limit)
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


@dataclass
class TagResult:
    n_tag_games: int
    candidates: list[Game]
    analyses: list[Analysis] = field(default_factory=list)
    not_games: list[str] = field(default_factory=list)
    unlisted: list[str] = field(default_factory=list)
    n_enough_reviews: int = 0  # games with >= min_reviews (explains "0 candidates")
    failed: list[tuple[str, str]] = field(default_factory=list)  # (game name, friendly reason)


def run_tag(
    http: HttpClient,
    tag: str,
    min_reviews: int,
    lo: float,
    hi: float,
    max_games: int,
    review_limit: int,
    on_step: Callable[[str, int, int], None] | None = None,
) -> TagResult | None:
    """Steps 1-4 for a tag. Returns None if SteamSpy knows no games for the tag.

    Games are analyzed in parallel (config.ANALYZE_WORKERS), starting as soon as each one passes
    the store-type check; the shared HttpClient keeps every host within its rate limit.
    on_step(message, done, total) is always called from the calling thread.
    """
    games = steamspy.games_by_tag(http, tag)
    if not games:
        return None
    candidates = filter_candidates(games, min_reviews, lo, hi)
    result = TagResult(
        n_tag_games=len(games),
        candidates=candidates,
        n_enough_reviews=sum(g.reviews >= min_reviews for g in games),
    )
    by_demand = sorted(candidates, key=lambda g: -g.reviews)
    n_check = min(max_games, len(by_demand))

    futures = {}  # future -> game, in the order the games were kept
    with ThreadPoolExecutor(max_workers=config.ANALYZE_WORKERS) as pool:

        def done() -> int:
            return sum(f.done() for f in futures)

        def checking(g: Game) -> None:
            if on_step:
                on_step(f"Checking store type: {g.name}", done(), n_check)

        def start(g: Game) -> None:
            futures[pool.submit(analyze_game, http, g.appid, review_limit)] = g

        hits, result.not_games, unlisted = verify_games(http, by_demand, max_games, checking, start)
        result.unlisted = [g.name for g in hits if g.appid in unlisted]
        for i, f in enumerate(as_completed(futures), 1):
            if on_step:
                on_step(f"Analyzed {futures[f].name}", i, len(hits))

    for f, g in futures.items():  # keep the deterministic order of `hits`
        try:
            a = f.result()
        except Exception as e:  # one broken game must not sink the whole run
            result.failed.append((g.name, friendly_error(e).message))
            continue
        if a is not None:
            result.analyses.append(a)
    return result
