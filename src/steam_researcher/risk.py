"""Deceptive-metric and feasibility checks (guide section 5)."""

import datetime as dt
import time
from statistics import median

from . import config
from .models import AppDetails, Game, HistPoint, MiningResult, RiskFlag


def _period(ts: int) -> str:
    return dt.datetime.fromtimestamp(ts, dt.UTC).strftime("%Y-%m")


def find_spikes(hist: list[HistPoint]) -> list[HistPoint]:
    """Periods after the launch window that dwarf the typical period."""
    total = sum(p.total for p in hist)
    if total == 0 or len(hist) <= config.SPIKE_LAUNCH_PERIODS + 2:
        return []
    med = median(p.total for p in hist) or 1
    return [
        p
        for p in hist[config.SPIKE_LAUNCH_PERIODS:]
        if p.total >= config.SPIKE_MIN_REVIEWS
        and p.total >= config.SPIKE_MEDIAN_FACTOR * med
        and p.total >= config.SPIKE_MIN_SHARE * total
    ]


def check_spikes(hist: list[HistPoint]) -> list[RiskFlag]:
    flags = []
    spikes = find_spikes(hist)
    total = sum(p.total for p in hist)
    for p in spikes:
        share = p.total / total
        neg = p.down / p.total
        if neg >= config.SPIKE_BOMB_NEGATIVE_SHARE:
            flags.append(RiskFlag(
                code="review_bomb", severity="high",
                message=f"{_period(p.date)}: {p.total:,} reviews ({share:.0%} of all), "
                f"{neg:.0%} negative. Likely a review bomb or controversy, not poor execution.",
            ))
        else:
            flags.append(RiskFlag(
                code="streamer_spike", severity="warn",
                message=f"{_period(p.date)}: {p.total:,} reviews ({share:.0%} of all) in one period. "
                "Check whether a streamer/viral moment drove demand.",
            ))
    if spikes:
        up = sum(p.up for p in hist) - sum(p.up for p in spikes)
        rest = total - sum(p.total for p in spikes)
        if rest:
            flags.append(RiskFlag(
                code="rating_without_spikes", severity="info",
                message=f"Excluding spike periods: {rest:,} reviews, {100 * up / rest:.0f}% positive.",
            ))
    return flags


def rating_without_bombs(hist: list[HistPoint]) -> float | None:
    """% positive with review-bomb periods removed; None if there was no bomb."""
    bombs = [p for p in find_spikes(hist) if p.down / p.total >= config.SPIKE_BOMB_NEGATIVE_SHARE]
    rest = sum(p.total for p in hist) - sum(p.total for p in bombs)
    if not bombs or not rest:
        return None
    return 100 * (sum(p.up for p in hist) - sum(p.up for p in bombs)) / rest


YEAR = 365 * 24 * 3600


def recent_activity(hist: list[HistPoint], now: float | None = None) -> tuple[int, int, float]:
    """(reviews in the last 12 months, all reviews, years since the first review) from the histogram."""
    if not hist:
        return 0, 0, 0.0
    now = time.time() if now is None else now
    recent = sum(p.total for p in hist if p.date >= now - YEAR)
    return recent, sum(p.total for p in hist), (now - hist[0].date) / YEAR


def check_fading(hist: list[HistPoint], now: float | None = None) -> list[RiskFlag]:
    """An old game whose audience has mostly moved on: the demand is history, not a market."""
    recent, total, age = recent_activity(hist, now)
    if not total or age < config.FADING_MIN_AGE_YEARS or recent / total >= config.FADING_SHARE:
        return []
    return [RiskFlag(
        code="fading_demand", severity="warn",
        message=f"Only {recent / total:.1%} of its reviews ({recent:,}) came in the last 12 months. "
        "The audience may have moved on.",
    )]


def check_discount(game: Game, details: AppDetails | None) -> list[RiskFlag]:
    # Without real price history (ITAD, later) we can only look at the current price.
    discount = details.discount_percent if details else game.discount
    final = (details.price_final_cents if details else game.price_cents) / 100
    flags = []
    if discount >= config.DEEP_DISCOUNT_PERCENT:
        flags.append(RiskFlag(
            code="deep_discount", severity="warn",
            message=f"Currently {discount}% off. Review counts may be inflated by deep sales.",
        ))
    if 0 < final < config.CHEAP_PRICE_USD:
        flags.append(RiskFlag(
            code="cheap_price", severity="warn",
            message=f"Sells for ${final:.2f}. Low price inflates units and reviews.",
        ))
    return flags


def check_complexity(details: AppDetails | None, tags: dict[str, int]) -> list[RiskFlag]:
    flags = []
    if details:
        online = [config.NETCODE_CATEGORY_IDS[c] for c in details.category_ids
                  if c in config.NETCODE_CATEGORY_IDS]
        if online:
            flags.append(RiskFlag(
                code="netcode", severity="warn",
                message=f"Online multiplayer ({', '.join(online)}): needs netcode, hard for small teams.",
            ))
    hard = sorted(config.HARD_TAGS & tags.keys())
    if hard:
        flags.append(RiskFlag(
            code="hard_tech", severity="info",
            message=f"Tags {', '.join(hard)}: technically demanding to do well.",
        ))
    return flags


def check_niche(tags: dict[str, int]) -> list[RiskFlag]:
    niche = sorted(config.NICHE_TAGS & tags.keys())
    if not niche:
        return []
    return [RiskFlag(
        code="niche", severity="warn",
        message=f"Tags {', '.join(niche)}: niche audience, harder to reach and market to.",
    )]


def check_listing(details: AppDetails | None) -> list[RiskFlag]:
    if details is None:
        return [RiskFlag(
            code="unlisted", severity="info",
            message="No store data (delisted or region-locked). The audience may be orphaned; verify manually.",
        )]
    if details.type != "game":
        return [RiskFlag(code="not_game", severity="high", message=f"Store type is {details.type!r}, not a game.")]
    return []


def check_scope(mining: MiningResult) -> list[RiskFlag]:
    """Players comparing the game to AAA titles: expectations a small team can't meet."""
    scope = next((c for c in mining.categories if c.code == "scope_unrealistic"), None)
    if scope is None or scope.share < config.SCOPE_MIN_SHARE:
        return []
    return [RiskFlag(
        code="scope_unrealistic", severity="warn",
        message=f"{scope.share:.0%} of negative reviews compare it to AAA games (GTA etc.). "
        "Part of the disappointment is scope an indie can't deliver.",
    )]


def assess(game: Game, details: AppDetails | None, hist: list[HistPoint]) -> list[RiskFlag]:
    return (
        check_listing(details)
        + check_spikes(hist)
        + check_fading(hist)
        + check_discount(game, details)
        + check_complexity(details, game.tags)
        + check_niche(game.tags)
    )
