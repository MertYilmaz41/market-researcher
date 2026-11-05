"""Market view of a whole tag: is this audience underserved, or already served by good games?

Pure: works on the game list a tag search already returned, so it costs no extra requests.
The list comes from SteamSpy (or Steam's store search) and may include a few non-games.
"""

from statistics import median

from pydantic import BaseModel

from . import boxmethod, config
from .i18n import _
from .models import Game
from .report import money


class MarketStats(BaseModel):
    n_games: int  # every game with the tag(s)
    n_demand: int  # games with >= min_reviews reviews
    n_underserved: int  # demand games inside the lo-hi % positive range
    n_well_served: int  # demand games at >= WELL_SERVED_RATING % positive
    median_rating: float  # % positive of the median demand game (0 if none)
    underserved_gross: float  # Box Method x45 gross of the underserved games, USD
    gap: float  # n_underserved / (n_underserved + n_well_served); 0 if both are 0


def market_stats(games: list[Game], min_reviews: int, lo: float, hi: float) -> MarketStats:
    demand = [g for g in games if g.reviews >= min_reviews]
    under = [g for g in demand if lo <= g.rating <= hi]
    well = [g for g in demand if g.rating >= config.WELL_SERVED_RATING]
    pair = len(under) + len(well)
    return MarketStats(
        n_games=len(games),
        n_demand=len(demand),
        n_underserved=len(under),
        n_well_served=len(well),
        median_rating=median(g.rating for g in demand) if demand else 0.0,
        underserved_gross=sum(boxmethod.estimate(g.reviews, g.base_price).gross_mid for g in under),
        gap=len(under) / pair if pair else 0.0,
    )


def summary(m: MarketStats) -> str:
    """One line for the CLI and the report (no symbols outside cp1254: the Windows console)."""
    return _("{games:,} games, {demand:,} with demand, {under:,} underserved, {well:,} well served "
             "(gap {gap:.0%}), {gross} underserved gross", games=m.n_games, demand=m.n_demand,
             under=m.n_underserved, well=m.n_well_served, gap=m.gap, gross=money(m.underserved_gross))


class TagMarket(BaseModel):
    tag: str
    stats: MarketStats
