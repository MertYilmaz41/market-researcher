"""A game's price in every Steam store region, in US dollars and against the US price (pure)."""

from pydantic import BaseModel

from .i18n import N_, _
from .models import RegionalPrice


# The report's country names (the web page uses the browser's Intl.DisplayNames instead).
COUNTRY_NAMES = {
    "us": N_("United States"),
    "ca": N_("Canada"),
    "mx": N_("Mexico"),
    "br": N_("Brazil"),
    "ar": N_("Argentina"),
    "cl": N_("Chile"),
    "co": N_("Colombia"),
    "pe": N_("Peru"),
    "uy": N_("Uruguay"),
    "cr": N_("Costa Rica"),
    "gb": N_("United Kingdom"),
    "de": N_("Germany"),
    "ch": N_("Switzerland"),
    "no": N_("Norway"),
    "pl": N_("Poland"),
    "ua": N_("Ukraine"),
    "ru": N_("Russia"),
    "kz": N_("Kazakhstan"),
    "az": N_("Azerbaijan"),
    "tr": N_("Turkey"),
    "il": N_("Israel"),
    "sa": N_("Saudi Arabia"),
    "ae": N_("United Arab Emirates"),
    "qa": N_("Qatar"),
    "kw": N_("Kuwait"),
    "za": N_("South Africa"),
    "in": N_("India"),
    "pk": N_("Pakistan"),
    "id": N_("Indonesia"),
    "my": N_("Malaysia"),
    "sg": N_("Singapore"),
    "ph": N_("Philippines"),
    "th": N_("Thailand"),
    "vn": N_("Vietnam"),
    "cn": N_("China"),
    "hk": N_("Hong Kong"),
    "tw": N_("Taiwan"),
    "jp": N_("Japan"),
    "kr": N_("South Korea"),
    "au": N_("Australia"),
    "nz": N_("New Zealand"),
}


def country_name(country: str) -> str:
    return _(COUNTRY_NAMES[country]) if country in COUNTRY_NAMES else country.upper()


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
