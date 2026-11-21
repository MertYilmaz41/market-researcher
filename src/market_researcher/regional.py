"""A game's price in every Steam store region, in US dollars and against the US price (pure)."""

from pydantic import BaseModel

from .models import RegionalPrice


class PriceRow(BaseModel):
    country: str
    price: RegionalPrice | None  # None: not sold there
    usd: float | None = None  # undiscounted price in US dollars; None without a rate
    vs_us: float | None = None  # usd / the US undiscounted price - 1 (-0.4 = 40% cheaper)


def compare(prices: dict[str, RegionalPrice | None], rates: dict[str, float]) -> list[PriceRow]:
    """Undiscounted prices (like the Box Method), cheapest in dollars first; countries without a dollar
    figure next, then those where the game isn't sold."""
    rows = []
    for country, p in prices.items():
        rate = rates.get(p.currency) if p else None
        rows.append(PriceRow(country=country, price=p, usd=p.initial_cents / 100 / rate if rate else None))
    us = next((r.usd for r in rows if r.country == "us"), None)
    for r in rows:
        if us and r.usd is not None:
            r.vs_us = r.usd / us - 1
    return sorted(rows, key=lambda r: (r.price is None, r.usd is None, r.usd or 0))
