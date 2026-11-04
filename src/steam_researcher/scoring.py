"""Opportunity score: Proven Demand + Poor Execution = High Opportunity."""

import math

from . import config
from .models import Game, MiningResult, Opportunity, RiskFlag


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


def score(
    game: Game,
    flags: list[RiskFlag],
    mining: MiningResult | None,
    adjusted_rating: float | None = None,
) -> Opportunity:
    rating = adjusted_rating if adjusted_rating is not None else game.rating
    fix = mining.fixability if mining and mining.categories else config.DEFAULT_FIXABILITY
    parts = {"demand": demand(game.reviews), "dissatisfaction": dissatisfaction(rating), "fixability": fix}

    w = config.SCORE_WEIGHTS
    if any(parts[k] == 0 for k in w):
        base = 0.0
    else:
        base = 100 * math.exp(sum(w[k] * math.log(parts[k]) for k in w) / sum(w.values()))

    penalized = [f.code for f in flags if f.code in config.RISK_PENALTIES]
    penalty = sum(config.RISK_PENALTIES[c] for c in penalized)
    return Opportunity(
        score=max(0.0, base - penalty),
        effective_rating=rating,
        penalty=penalty,
        penalized=penalized,
        **parts,
    )
