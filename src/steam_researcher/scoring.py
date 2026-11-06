"""Opportunity score: Proven Demand + Poor Execution = High Opportunity."""

import math

from . import config
from .i18n import N_, _
from .models import Analysis, Game, MiningResult, Opportunity, RiskFlag


def _clamp(x: float) -> float:
    return max(0.0, min(1.0, x))


def demand(reviews: int) -> float:
    if reviews <= 0:
        return 0.0
    span = config.DEMAND_LOG_MAX - config.DEMAND_LOG_MIN
    return _clamp((math.log10(reviews) - config.DEMAND_LOG_MIN) / span)


def dissatisfaction(rating: float) -> float:
    """1 at MIN_RATING (5%), 0 at MAX_RATING (70%) and above."""
    return _clamp((config.MAX_RATING - rating) / (config.MAX_RATING - config.MIN_RATING))


def combine(parts: dict[str, float]) -> float:
    """100 x the weighted geometric mean of the [0,1] parts; 0 if any part is 0."""
    w = config.SCORE_WEIGHTS
    if any(parts[k] == 0 for k in w):
        return 0.0
    return 100 * math.exp(sum(w[k] * math.log(parts[k]) for k in w) / sum(w.values()))


def score(
    game: Game,
    flags: list[RiskFlag],
    mining: MiningResult | None,
    adjusted_rating: float | None = None,
) -> Opportunity:
    rating = adjusted_rating if adjusted_rating is not None else game.rating
    fix = mining.fixability if mining and mining.categories else config.DEFAULT_FIXABILITY
    parts = {"demand": demand(game.reviews), "dissatisfaction": dissatisfaction(rating), "fixability": fix}

    base = combine(parts)
    penalized = [f.code for f in flags if f.code in config.RISK_PENALTIES]
    penalty = sum(config.RISK_PENALTIES[c] for c in penalized)
    return Opportunity(
        score=max(0.0, base - penalty),
        effective_rating=rating,
        penalty=penalty,
        penalized=penalized,
        **parts,
    )


PART_LABELS = {"demand": N_("Demand"), "dissatisfaction": N_("Dissatisfaction"), "fixability": N_("Fixability")}


def explain(a: Analysis) -> dict:
    """How a game's score was reached, in plain words (current language), for the web UI's score card."""
    o, g = a.opportunity, a.game
    lo_reviews, hi_reviews = round(10 ** config.DEMAND_LOG_MIN), round(10 ** config.DEMAND_LOG_MAX)
    rating = _("{rating:.0f}% positive", rating=g.rating)
    if round(o.effective_rating) != round(g.rating):
        rating += _(" ({adjusted:.0f}% with review-bomb periods removed)", adjusted=o.effective_rating)
    mined = a.mining is not None and bool(a.mining.categories)
    basis = {
        "demand": _("{n:,} reviews. Log scale: {lo} reviews = 0%, {hi:,}+ = 100%.",
                    n=g.reviews, lo=lo_reviews, hi=hi_reviews),
        "dissatisfaction": _("{rating}. {max:g}%+ positive = 0%, {min:g}% = 100%.",
                             rating=rating, max=config.MAX_RATING, min=config.MIN_RATING),
        "fixability": (_("{fix:.0%} of complaint mentions are things a small team can fix "
                         "(bugs, UI, performance...), not scope or genre.", fix=o.fixability) if mined else
                       _("Reviews couldn't be mined, so {fix:.0%} is assumed.", fix=config.DEFAULT_FIXABILITY)
                       if a.mining is None else
                       _("Reviews were read, but none matched a complaint category, so {fix:.0%} is assumed.",
                         fix=config.DEFAULT_FIXABILITY)),
    }
    parts = [{"key": k, "label": _(PART_LABELS[k]), "value": getattr(o, k), "weight": w, "basis": basis[k]}
             for k, w in config.SCORE_WEIGHTS.items()]
    reasons = {f.code: f.text() for f in a.flags}
    return {
        "score": o.score,
        "parts": parts,
        "combined": combine({p["key"]: p["value"] for p in parts}),
        "penalties": [{"code": c, "label": _(config.RISK_LABELS.get(c, c)), "points": config.RISK_PENALTIES[c],
                       "reason": reasons.get(c, "")} for c in o.penalized],
        "zero_part": next((p["label"] for p in parts if p["value"] == 0), None),
    }
