"""Deceptive-metric and feasibility checks (guide section 5)."""

import datetime as dt
import time
from statistics import median

from . import config
from .i18n import N_, _
from .models import Analysis, AppDetails, Game, HistPoint, MiningResult, RiskFlag


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
            flags.append(RiskFlag.make(
                "review_bomb", "high",
                N_("{period}: {n:,} reviews ({share:.0%} of all), {neg:.0%} negative. "
                   "Likely a review bomb or controversy, not poor execution."),
                period=_period(p.date), n=p.total, share=share, neg=neg,
            ))
        else:
            flags.append(RiskFlag.make(
                "streamer_spike", "warn",
                N_("{period}: {n:,} reviews ({share:.0%} of all) in one period. A sale, an update, a streamer "
                   "or a viral moment may have caused it; check before reading it as lasting demand."),
                period=_period(p.date), n=p.total, share=share,
            ))
    if spikes:
        up = sum(p.up for p in hist) - sum(p.up for p in spikes)
        rest = total - sum(p.total for p in spikes)
        if rest:
            flags.append(RiskFlag.make(
                "rating_without_spikes", "info",
                N_("Excluding spike periods: {n:,} reviews, {rating:.0f}% positive."),
                n=rest, rating=100 * up / rest,
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


def recent_rating(hist: list[HistPoint], now: float | None = None) -> float | None:
    """% positive of the reviews from the last 12 months (histogram, all languages); None if none."""
    now = time.time() if now is None else now
    recent = [p for p in hist if p.date >= now - YEAR]
    total = sum(p.total for p in recent)
    return 100 * sum(p.up for p in recent) / total if total else None


def check_recovered(hist: list[HistPoint], now: float | None = None) -> list[RiskFlag]:
    """Players rate it much better lately: the problems may already be fixed (by a patch or an update),
    so the audience is no longer waiting for someone else to fix them."""
    recent, total, _ = recent_activity(hist, now)
    lately = recent_rating(hist, now)
    if lately is None or recent < config.RECOVERED_MIN_RECENT:
        return []
    overall = 100 * sum(p.up for p in hist) / total
    if lately < overall + config.RECOVERED_DELTA and lately < config.MAX_RATING:
        return []
    return [RiskFlag.make(
        "recovered", "warn",
        N_("Rated {lately:.0f}% positive in the last 12 months vs {overall:.0f}% all time "
           "({n:,} recent reviews): the problems may already be fixed."),
        lately=lately, overall=overall, n=recent,
    )]


def check_fading(hist: list[HistPoint], now: float | None = None) -> list[RiskFlag]:
    """An old game whose audience has mostly moved on: the demand is history, not a market."""
    recent, total, age = recent_activity(hist, now)
    if not total or age < config.FADING_MIN_AGE_YEARS or recent / total >= config.FADING_SHARE:
        return []
    return [RiskFlag.make(
        "fading_demand", "warn",
        N_("Only {share:.1%} of its reviews ({n:,}) came in the last 12 months. The audience may have moved on."),
        share=recent / total, n=recent,
    )]


def check_discount(game: Game, details: AppDetails | None) -> list[RiskFlag]:
    # Without real price history (ITAD, later) we can only look at the current price.
    discount = details.discount_percent if details else game.discount
    final = (details.price_final_cents if details else game.price_cents) / 100
    flags = []
    if discount >= config.DEEP_DISCOUNT_PERCENT:
        flags.append(RiskFlag.make(
            "deep_discount", "warn",
            N_("Currently {discount}% off. Review counts may be inflated by deep sales."), discount=discount,
        ))
    if 0 < final < config.CHEAP_PRICE_USD:
        flags.append(RiskFlag.make(
            "cheap_price", "warn",
            N_("Sells for ${price:.2f}. Low price inflates units and reviews."), price=final,
        ))
    return flags


def check_complexity(details: AppDetails | None, tags: dict[str, int]) -> list[RiskFlag]:
    flags = []
    if details:
        online = [config.NETCODE_CATEGORY_IDS[c] for c in details.category_ids
                  if c in config.NETCODE_CATEGORY_IDS]
        if online:
            flags.append(RiskFlag.make(
                "netcode", "warn",
                N_("Online multiplayer ({modes}): needs netcode, hard for small teams."), modes=", ".join(online),
            ))
    hard = sorted(config.HARD_TAGS & tags.keys())
    if hard:
        flags.append(RiskFlag.make(
            "hard_tech", "info", N_("Tags {tags}: technically demanding to do well."), tags=", ".join(hard),
        ))
    return flags


def check_niche(tags: dict[str, int]) -> list[RiskFlag]:
    niche = sorted(config.NICHE_TAGS & tags.keys())
    if not niche:
        return []
    return [RiskFlag.make(
        "niche", "warn", N_("Tags {tags}: niche audience, harder to reach and market to."), tags=", ".join(niche),
    )]


def check_listing(details: AppDetails | None) -> list[RiskFlag]:
    if details is None:
        return [RiskFlag.make(
            "unlisted", "info",
            N_("No store data (delisted or region-locked). The audience may be orphaned; verify manually."),
        )]
    if details.type != "game":
        return [RiskFlag.make("not_game", "high", N_("Store type is '{type}', not a game."), type=details.type)]
    return []


def check_scope(mining: MiningResult) -> list[RiskFlag]:
    """Players comparing the game to AAA titles: expectations a small team can't meet."""
    scope = next((c for c in mining.categories if c.code == "scope_unrealistic"), None)
    if scope is None or scope.share < config.SCOPE_MIN_SHARE:
        return []
    return [RiskFlag.make(
        "scope_unrealistic", "warn",
        N_("{share:.0%} of negative reviews compare it to AAA games (GTA etc.). "
           "Part of the disappointment is scope an indie can't deliver."),
        share=scope.share,
    )]


def assess(game: Game, details: AppDetails | None, hist: list[HistPoint]) -> list[RiskFlag]:
    return (
        check_listing(details)
        + check_spikes(hist)
        + check_fading(hist)
        + check_recovered(hist)
        + check_discount(game, details)
        + check_complexity(details, game.tags)
        + check_niche(game.tags)
    )


# Not shown in the list of checks: the first only adjusts the rating, the others drop or flag a game
# that never reaches the ranking's normal view.
_NOT_CHECKS = {"rating_without_spikes", "not_game", "unlisted"}


def checks(a: Analysis) -> list[dict]:
    """Every risk check and how this game came out of it (current language), for the web UI's History tab:
    {code, label, flagged, severity, points, detail}. A flagged check's detail is its message; a passed
    one says briefly why it passed."""
    flags = {f.code: f for f in a.flags}
    recent, total, _age = recent_activity(a.histogram, a.analyzed_at)
    lately = recent_rating(a.histogram, a.analyzed_at)
    discount = a.details.discount_percent if a.details else a.game.discount
    final = (a.details.price_final_cents if a.details else a.game.price_cents) / 100
    passed = {
        "review_bomb": _("none"),
        "streamer_spike": _("none"),
        "deep_discount": _("full price") if not discount else _("{d}% off", d=discount),
        "cheap_price": _("free to play") if final <= 0 else _("${price:.2f}", price=final),
        "netcode": _("no online modes"),
        "niche": _("no niche tags"),
        "scope_unrealistic": _("few AAA comparisons") if a.mining else _("reviews not read"),
        "hard_tech": _("no demanding tags"),
        "fading_demand": (_("{share:.1%} of reviews in the last 12 months", share=recent / total) if total
                          else _("no review history")),
        "recovered": (_("too few recent reviews") if lately is None or recent < config.RECOVERED_MIN_RECENT
                      else _("last 12 months: {lately:.0f}% positive", lately=lately)),
    }
    out = []
    for code, label in config.RISK_LABELS.items():
        if code in _NOT_CHECKS:
            continue
        f = flags.get(code)
        out.append({
            "code": code, "label": _(label), "flagged": f is not None,
            "severity": f.severity if f else None,
            "points": config.RISK_PENALTIES.get(code, 0) if f else 0,
            "detail": f.text() if f else passed.get(code, ""),
        })
    return out
