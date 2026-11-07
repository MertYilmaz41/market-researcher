"""Market view of a whole tag: is this audience underserved, or already served by good games?

Pure: works on the game list a tag search already returned, so it costs no extra requests.
The list comes from SteamSpy (or Steam's store search) and may include a few non-games.
"""

from statistics import median, quantiles

from pydantic import BaseModel

from . import boxmethod, config
from .i18n import _
from .models import Game
from .report import fmt_price, money

MIN_PRICED = 3  # paid games needed before a price range is shown


class MarketStats(BaseModel):
    n_games: int  # every game with the tag(s)
    n_demand: int  # games with >= min_reviews reviews
    n_underserved: int  # demand games inside the lo-hi % positive range
    n_well_served: int  # demand games at >= WELL_SERVED_RATING % positive
    median_rating: float  # % positive of the median demand game (0 if none)
    underserved_gross: float  # Box Method x45 gross of the underserved games, USD
    gap: float  # n_underserved / (n_underserved + n_well_served); 0 if both are 0
    # What the paid games with demand cost (undiscounted, USD): the price range a new game for this
    # audience would sit in. Today's list price, so old games that were cut since pull it down.
    # None with fewer than MIN_PRICED paid games, and in runs saved before these fields existed.
    n_priced: int | None = None
    price_median: float | None = None
    price_p25: float | None = None
    price_p75: float | None = None
    well_served_price_median: float | None = None  # the same for the well-served games alone


def market_stats(games: list[Game], min_reviews: int, lo: float, hi: float) -> MarketStats:
    demand = [g for g in games if g.reviews >= min_reviews]
    under = [g for g in demand if lo <= g.rating <= hi]
    well = [g for g in demand if g.rating >= config.WELL_SERVED_RATING]
    pair = len(under) + len(well)
    prices = sorted(g.base_price for g in demand if g.base_price > 0)
    well_prices = [g.base_price for g in well if g.base_price > 0]
    enough = len(prices) >= MIN_PRICED
    p25, _p50, p75 = quantiles(prices, n=4, method="inclusive") if enough else (None, None, None)
    return MarketStats(
        n_games=len(games),
        n_demand=len(demand),
        n_underserved=len(under),
        n_well_served=len(well),
        median_rating=median(g.rating for g in demand) if demand else 0.0,
        underserved_gross=sum(boxmethod.estimate(g.reviews, g.base_price).gross_mid for g in under),
        gap=len(under) / pair if pair else 0.0,
        n_priced=len(prices),
        price_median=median(prices) if enough else None,
        price_p25=p25,
        price_p75=p75,
        well_served_price_median=median(well_prices) if len(well_prices) >= MIN_PRICED else None,
    )


def summary(m: MarketStats) -> str:
    """One line for the CLI and the report (no symbols outside cp1254: the Windows console)."""
    return _("{games:,} games, {demand:,} with demand, {under:,} underserved, {well:,} well served "
             "(unmet share {gap:.0%}), {gross} underserved revenue", games=m.n_games, demand=m.n_demand,
             under=m.n_underserved, well=m.n_well_served, gap=m.gap, gross=money(m.underserved_gross)) + price_text(m)


def price_text(m: MarketStats) -> str:
    """", median price $14.99 (middle half $9.99-$19.99; well served $17.99)", or "" without enough prices."""
    if m.price_median is None:
        return ""
    text = _(", median price {median} (middle half {lo}-{hi}", median=fmt_price(m.price_median),
             lo=fmt_price(m.price_p25), hi=fmt_price(m.price_p75))
    if m.well_served_price_median is not None:
        text += _("; well served {price}", price=fmt_price(m.well_served_price_median))
    return text + ")"


class TagMarket(BaseModel):
    tag: str
    stats: MarketStats


class TrackRecord(BaseModel):
    """How the tag's games released 48-24 months ago did in their first 24 months: the backtest's strongest
    signal ("earlier entrants' hit rate", rho +0.47; reports/backtest.md). Hit: >= 500 reviews at >= 80%."""
    start: int  # first month of the release window (backtest month index: year * 12 + month - 1)
    months: int = 24
    entrants: int = 0
    hits: int = 0
    sold: int = 0  # >= 500 reviews, any rating
    measured_at: float = 0.0
    too_broad: int | None = None  # not measured: the tag has this many games with 10+ reviews

    @property
    def hit_rate(self) -> float:
        return self.hits / self.entrants if self.entrants else 0.0

    def window(self) -> tuple[str, str]:
        """("2022-11", "2024-10"): the first and last release month."""
        end = self.start + self.months - 1
        return f"{self.start // 12}-{self.start % 12 + 1:02d}", f"{end // 12}-{end % 12 + 1:02d}"


MIN_TRACK_ENTRANTS = 10  # the backtest's floor: fewer releases say too little


def track_text(tr: TrackRecord) -> str:
    """One sentence for the CLI, the report and the web (no symbols outside cp1254)."""
    if tr.too_broad is not None:
        return _("Track record: not measured; the tag is too broad ({n:,} games with 10+ reviews).", n=tr.too_broad)
    first, last = tr.window()
    if tr.entrants < MIN_TRACK_ENTRANTS:
        return _("Track record: only {n} games released {first} to {last}; too few to tell.",
                 n=tr.entrants, first=first, last=last)
    return _("Track record: {hits} of {n} games released {first} to {last} became hits ({rate:.0%}; "
             "500+ reviews at 80%+ positive in their first 2 years).",
             hits=tr.hits, n=tr.entrants, first=first, last=last, rate=tr.hit_rate)
