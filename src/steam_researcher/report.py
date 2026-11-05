"""Markdown opportunity report."""

import datetime as dt
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import boxmethod, risk
from .models import Analysis

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def money(x: float) -> str:
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


def recent_text(a: Analysis) -> str:
    """Reviews in the last 12 months and their share of all reviews (English histogram)."""
    recent, total, _ = risk.recent_activity(a.histogram)
    return f"{recent:,} ({recent / total:.0%})" if total else "-"


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
        money=money,
        pct=pct,
        box=box,
        gross=gross,
        top_complaint=top_complaint,
        risk_codes=risk_codes,
        recent_text=recent_text,
    )
    return re.sub(r"\n{3,}", "\n\n", text)  # template whitespace tidy-up


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"
