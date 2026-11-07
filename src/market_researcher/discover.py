"""Steps 1-3: tag -> demand filter -> satisfaction filter, sorted by rating ascending."""

from . import config
from .models import Game


def filter_candidates(
    games: list[Game],
    min_reviews: int = config.MIN_REVIEWS,
    min_rating: float = config.MIN_RATING,
    max_rating: float = config.MAX_RATING,
) -> list[Game]:
    hits = [
        g
        for g in games
        if g.reviews >= min_reviews and min_rating <= g.rating <= max_rating
    ]
    return sorted(hits, key=lambda g: g.rating)


def parse_rating_range(text: str) -> tuple[float, float]:
    """Parse 'LO-HI' (percent positive). Raises ValueError on bad input."""
    lo_s, sep, hi_s = text.partition("-")
    try:
        if not sep:
            raise ValueError
        lo, hi = float(lo_s), float(hi_s)
    except ValueError:
        raise ValueError(f"expected LO-HI like 5-70, got {text!r}") from None
    if not 0 <= lo <= hi <= 100:
        raise ValueError(f"need 0 <= LO <= HI <= 100, got {text!r}")
    return lo, hi
