"""Markdown opportunity report."""

import csv
import datetime as dt
import io
import re
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from . import boxmethod, config, risk
from .i18n import N_, _, fmt, lang, num
from .models import Analysis, Game, GameSummary, OpportunitySummary

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    undefined=StrictUndefined,
    trim_blocks=False,
    lstrip_blocks=False,
    keep_trailing_newline=True,
)


def money(x: float) -> str:
    if x >= 1_000_000_000:
        return fmt("${x:.1f}B", x=x / 1_000_000_000)
    if x >= 1_000_000:
        return fmt("${x:.1f}M", x=x / 1_000_000)
    if x >= 1_000:
        return f"${x / 1_000:.0f}k"
    return f"${x:.0f}"


def md(text: object) -> str:
    """Make arbitrary text safe inside Markdown table cells and quotes."""
    return re.sub(r"\s+", " ", str(text)).replace("|", "\\|").strip()


def pct(x: float) -> str:
    return fmt("{x:.0%}", x=x)


def percent(rating: float) -> str:
    """A 0-100 rating: 40% / %40."""
    return fmt("{x:.0%}", x=rating / 100)


def fmt_price(price: float) -> str:
    return fmt("${x:.2f}", x=price)


SEVERITY_NAMES = {"high": N_("Serious"), "warn": N_("Caution"), "info": N_("Note")}


def severity(level: str) -> str:
    return _(SEVERITY_NAMES.get(level, level))


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
    recent, total, _age = risk.recent_activity(a.histogram, a.analyzed_at)
    if not total:
        return "-"
    lately = risk.recent_rating(a.histogram, a.analyzed_at)
    text = _("{n:,} ({share:.0%})", n=recent, share=recent / total)
    return text + (_(", {rating:.0f}% positive", rating=lately) if lately is not None else "")


def risk_codes(a: Analysis) -> str:
    codes = [f.code for f in a.flags if f.severity != "info"]
    return ", ".join(codes) or "-"


def risk_label(code: str) -> str:
    """A risk flag's name in the report language; English reports keep the code (deep_discount)."""
    return _(config.RISK_LABELS.get(code, code)) if lang() == "tr" else code


def risk_names(a: Analysis) -> str:
    return ", ".join(risk_label(f.code) for f in a.flags if f.severity != "info") or "-"


def complaint_text(a: Analysis) -> str:
    """The top complaint with its share, in the report language (top_complaint stays English for the CSV)."""
    if not a.mining or not a.mining.categories:
        return "-"
    c = a.mining.categories[0]
    return f"{_(c.label)} ({pct(c.share)})"


def lower(text: str) -> str:
    """Lower case mid-sentence in English; Turkish text keeps its case (str.lower() gets I/ı wrong)."""
    return text.lower() if lang() == "en" else text


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
    track: str = "",  # market.track_text() of the tag, when it was measured
    summary: OpportunitySummary | None = None,  # the run's LLM summary in the report language
    game_summaries: dict[int, GameSummary] | None = None,  # appid -> LLM game summary in the report language
) -> str:
    _env.filters["md"] = md
    _env.filters["risk_label"] = risk_label
    _env.globals["_"] = _
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
        track=track,
        summary=summary,
        game_summaries=game_summaries or {},
        summary_games=min(config.SUMMARY_GAMES, len(rank(analyses))),
        well_served=config.WELL_SERVED_RATING,
        money=money,
        pct=pct,
        percent=percent,
        fmt_price=fmt_price,
        severity=severity,
        num=num,
        lower=lower,
        risk_label=risk_label,
        risk_names=risk_names,
        complaint_text=complaint_text,
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
        recent, total, _age = risk.recent_activity(a.histogram, a.analyzed_at)
        lately = risk.recent_rating(a.histogram, a.analyzed_at)
        w.writerow([
            i, a.game.appid, a.game.name, round(a.opportunity.score),
            "new" if a.game.appid in changes and change is None else ("" if change == "" else round(change)),
            a.game.reviews, round(a.game.rating), recent if total else "", "" if lately is None else round(lately),
            round(box(a).gross_mid) if a.game.base_price else "", top_complaint(a), risk_codes(a), a.game.store_url,
        ])
    return out.getvalue()


def shortlist_csv(items: list[dict]) -> str:
    """The shortlist (RunStore.shortlist) as CSV; labels stay English like the ranking CSV."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(["appid", "name", "score", "pct_positive", "reviews", "top_complaint", "from_search", "note",
                "starred", "store_url"])
    for g in items:
        complaint = f"{g['complaint']} ({g['complaint_share']:.0%})" if g.get("complaint") else "-"
        w.writerow([g["appid"], g["name"], round(g["score"]), round(g["rating"]), g["reviews"], complaint,
                    g["source"], g["note"], dt.date.fromtimestamp(g["added"]).isoformat(), g["store_url"]])
    return out.getvalue()


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "report"
