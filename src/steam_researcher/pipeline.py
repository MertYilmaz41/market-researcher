"""Shared steps used by `discover`, `analyze` and `report`."""

from collections.abc import Callable
from dataclasses import dataclass, field

from . import risk, scoring
from .http import HttpClient
from .mining import mine
from .discover import filter_candidates
from .models import Analysis, Game
from .sources import steam_store, steamspy


def verify_games(
    http: HttpClient,
    candidates: list[Game],
    limit: int,
    progress: Callable[[Game], None] | None = None,
) -> tuple[list[Game], list[str], set[int]]:
    """'Games Only': SteamSpy has no type field, so confirm with Steam appdetails.

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
    except RuntimeError as e:
        review_error = str(e)

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

    on_step(message, done, total) reports progress over verify + analyze steps.
    """
    games = steamspy.games_by_tag(http, tag)
    if not games:
        return None
    candidates = filter_candidates(games, min_reviews, lo, hi)
    result = TagResult(n_tag_games=len(games), candidates=candidates)
    by_demand = sorted(candidates, key=lambda g: -g.reviews)
    n_check = min(max_games, len(by_demand))

    checked = 0

    def checking(g: Game) -> None:
        nonlocal checked
        if on_step:
            on_step(f"Checking store type: {g.name}", checked, n_check)
        checked += 1

    hits, result.not_games, unlisted = verify_games(http, by_demand, max_games, checking)
    result.unlisted = [g.name for g in hits if g.appid in unlisted]
    for i, g in enumerate(hits):
        if on_step:
            on_step(f"Analyzing {g.name}", i, len(hits))
        if (a := analyze_game(http, g.appid, review_limit)) is not None:
            result.analyses.append(a)
    return result
