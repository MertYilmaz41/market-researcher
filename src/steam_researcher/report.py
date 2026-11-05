"""Markdown opportunity report."""

import csv
import datetime as dt
import io
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import boxmethod, config, risk
from .i18n import N_, _
from .models import Analysis, Game

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def money(x: float) -> str:
    if x >= 1_000_000_000:
        return f"${x / 1_000_000_000:.1f}B"
    if x >= 1_000_000:
        return f"${x / 1_000_000:.1f}M"
    if x >= 1_000:
        return f"${x / 1_000:.0f}k"
    return f"${x:.0f}"


def md(text: object) -> str:
    """Make arbitrary text safe inside Markdown table cells and quotes."""
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def pct(x: float) -> str:
    return f"{x:.0%}"


def box(a: Analysis):
    return boxmethod.estimate(a.game.reviews, a.game.base_price)


def gross(a: Analysis) -> str:
    return "F2P" if not a.game.base_price else money(box(a).gross_mid)


def top_complaint(a: Analysis) -> str:
    if not a.mining or not a.mining.categories:
        return "-"
    c = a.mining.categories[0]
    return f"{c.label} ({c.share:.0%})"


SOURCE_NAMES = {"steam": N_("Steam's own numbers"), "histogram": N_("Steam's review histogram"),
                "steamspy": N_("SteamSpy estimate")}


def rating_source_text(g: Game) -> str:
    """Where the review count and % positive come from, and SteamSpy's figure when it differs."""
    text = _(SOURCE_NAMES.get(g.rating_source, g.rating_source))
    if g.steamspy_rating is not None and abs(g.steamspy_rating - g.rating) >= 3:
        text += _(" (SteamSpy says {rating:.0f}%)", rating=g.steamspy_rating)
    if g.offtopic_reviews:
        text += _("; {n:,} reviews from review-bomb periods count toward demand, not % positive", n=g.offtopic_reviews)
    return text


def recent_text(a: Analysis) -> str:
    """Reviews in the last 12 months, their share of all reviews and their % positive (histogram)."""
    recent, total, _age = risk.recent_activity(a.histogram)
    if not total:
        return "-"
    lately = risk.recent_rating(a.histogram)
    text = _("{n:,} ({share:.0%})", n=recent, share=recent / total)
    return text + (_(", {rating:.0f}% positive", rating=lately) if lately is not None else "")


def risk_codes(a: Analysis) -> str:
    codes = [f.code for f in a.flags if f.severity != "info"]
    return ", ".join(codes) or "-"


def rank(analyses: list[Analysis]) -> list[Analysis]:
    kept = [a for a in analyses if not a.excluded]
    return sorted(kept, key=lambda a: -a.opportunity.score)


def render(
    *,
    tag: str,
    analyses: list[Analysis],
    n_candidates: int,
    n_tag_games: int,
    min_reviews: int,
    lo: float,
    hi: float,
    not_games: list[str],
    unlisted: list[str],
    market: str = "",  # market.summary() of the whole tag
) -> str:
    _env.filters["md"] = md
    template = _env.get_template("report.md.j2")
    text = template.render(
        tag=tag,
        date=dt.date.today().isoformat(),
        analyses=analyses,
        ranked=rank(analyses),
        n_candidates=n_candidates,
        n_tag_games=n_tag_games,
        min_reviews=min_reviews,
        lo=f"{lo:g}",
        hi=f"{hi:g}",
        not_games=not_games,
        unlisted=unlisted,
        market=market,
        well_served=config.WELL_SERVED_RATING,
        money=money,
        pct=pct,
        box=box,
        gross=gross,
        top_complaint=top_complaint,
        risk_codes=risk_codes,
        recent_text=recent_text,
        rating_source_text=rating_source_text,
    )
    return re.sub(r"\n{3,}", "\n\n", text)  # template whitespace tidy-up


def ranking_csv(ranked: list[Analysis], changes: dict[int, float | None] | None = None) -> str:
    """The ranking as CSV for spreadsheets. changes: appid -> score change (None = new), from runs.changes."""
    changes = changes or {}
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["rank", "appid", "name", "score", "score_change", "reviews", "pct_positive",
                "reviews_last_12_months", "pct_positive_last_12_months", "est_gross_x45", "top_complaint", "risks", "store_url"])
    for i, a in enumerate(ranked, 1):
        change = changes.get(a.game.appid, "")
        recent, total, _age = risk.recent_activity(a.histogram)
        lately = risk.recent_rating(a.histogram)
        w.writerow([
            i, a.game.appid, a.game.name, round(a.opportunity.score),
            "new" if a.game.appid in changes and change is None else ("" if change == "" else round(change)),
            a.game.reviews, round(a.game.rating), recent if total else "", "" if lately is None else round(lately),
            round(box(a).gross_mid) if a.game.base_price else "", top_complaint(a), risk_codes(a), a.game.store_url,
        ])
    return out.getvalue()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"
