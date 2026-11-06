import datetime as dt
import functools
import os
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from . import boxmethod, config, market, notices, runs, summary
from .cache import Cache
from .discover import filter_candidates, parse_rating_range
from .http import HttpClient
from .i18n import LANG, LANGS, _, fmt, lang, num
from .mining.llm import LLMUnavailable
from .models import Analysis, MiningResult
from .pipeline import TagResult, UnknownTag, analyze_game, run_markets, run_tag, tag_games, tag_label, verify_games
from .report import money, percent, rank, rating_source_text, recent_text, render, risk_label, severity, slug

app = typer.Typer(help="Find underserved Steam audiences (CodeMonkey's method).", no_args_is_help=True)
cache_app = typer.Typer(help="Manage the local cache.")
app.add_typer(cache_app, name="cache")
console = Console()


@app.callback()
def main(
    ctx: typer.Context,
    lang: str = typer.Option("en", "--lang", envvar="SR_LANG",
                             help="Output language: en or tr (also SR_LANG). Put it before the command: sr --lang tr report ..."),
):
    """Find underserved Steam audiences (CodeMonkey's method)."""
    if lang not in LANGS:
        raise typer.BadParameter(f"use one of: {', '.join(LANGS)}", param_hint="--lang")
    token = LANG.set(lang)
    ctx.call_on_close(lambda: LANG.reset(token))

SEVERITY_STYLE = {"high": "bold red", "warn": "yellow", "info": "cyan"}
NOTICE_STYLE = {"success": ("green", "OK"), "info": ("cyan", "i"), "warning": ("yellow", "!"), "error": ("bold red", "x")}


def _print_notice(n: notices.Notice) -> None:
    style, mark = NOTICE_STYLE[n.level]
    console.print(f"[{style}][{mark}] {n.title}:[/] {n.message}")
    if n.hint:
        console.print(f"    [dim]-> {n.hint}[/]")


def _print_notices(items: list[notices.Notice]) -> None:
    for n in items:
        _print_notice(n)


def _guarded(func):
    """Show network/service failures as a friendly message instead of a traceback (SR_DEBUG=1 to see it)."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        # typer.BadParameter: Typer bundles its own click, so it isn't a click.ClickException
        except (typer.Exit, typer.BadParameter, click.exceptions.Exit, click.exceptions.ClickException,
                click.exceptions.Abort, KeyboardInterrupt):
            raise
        except Exception as e:
            if os.environ.get("SR_DEBUG"):
                raise
            _print_notice(notices.friendly_error(e))
            raise typer.Exit(1) from None

    return wrapper


def _rating_range(rating: str) -> tuple[float, float]:
    try:
        return parse_rating_range(rating)
    except ValueError as e:
        raise typer.BadParameter(str(e), param_hint="--rating") from None


def _label(tags: list[str]) -> str:
    if len(tags) > config.MAX_TAGS:
        raise typer.BadParameter(_("use at most {n} tags", n=config.MAX_TAGS), param_hint="--tag")
    return tag_label(tags)


def _unknown_tag(http: HttpClient, e: UnknownTag):
    _print_notice(notices.unknown_tag(e.tag, notices.known_tags(http)))
    raise typer.Exit(1)


def _tag_games(http: HttpClient, tags: list[str], label: str):
    try:
        with console.status(_("Fetching games tagged '{tag}'...", tag=label)) as status:
            return tag_games(http, tags, lambda msg, done, total: status.update(
                _("{message} (page {done}/{total})", message=msg, done=done, total=total)))
    except UnknownTag as e:
        _unknown_tag(http, e)


TAG_OPT = typer.Option(
    ..., "--tag", "-t", help='Steam tag, e.g. "Job Simulator". Repeat it for games with all the tags: -t Crafting -t Survival'
)
RATING_OPT = typer.Option(
    f"{config.MIN_RATING:g}-{config.MAX_RATING:g}", "--rating", help="Allowed % positive range, LO-HI"
)
NO_CACHE_OPT = typer.Option(False, "--no-cache", help="Bypass the cache")


@app.command()
@_guarded
def discover(
    tag: list[str] = TAG_OPT,
    min_reviews: int = typer.Option(config.MIN_REVIEWS, min=1, help="Demand filter"),
    rating: str = RATING_OPT,
    top: int = typer.Option(30, min=1, help="Max rows to show"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Steps 1-3: list games in a tag with proven demand but weak satisfaction."""
    lo, hi = _rating_range(rating)
    label = _label(tag)
    _print_notices(notices.for_filters(min_reviews, lo, hi, 0, 0))
    http = HttpClient(use_cache=not no_cache)
    games = _tag_games(http, tag, label)
    stats = market.market_stats(games, min_reviews, lo, hi)
    console.print(f"[bold]{_('Market:')}[/] {market.summary(stats)}")
    candidates = filter_candidates(games, min_reviews, lo, hi)
    if not candidates:
        empty = TagResult(n_tag_games=len(games), candidates=[],
                          n_enough_reviews=sum(g.reviews >= min_reviews for g in games), market=stats)
        _print_notices(notices.for_tag_result(label, min_reviews, lo, hi, top, empty))
        raise typer.Exit(1)

    with console.status(_("Checking store type (games only)...")) as status:
        hits, not_games, unlisted = verify_games(
            http, candidates, top, lambda g: status.update(_("Checking store type: {name}", name=g.name))
        )

    table = Table(title=_("{tag}: {n} of {total} games with >={min} reviews and {lo:g}-{hi:g}% positive",
                          tag=label, n=len(candidates) - len(not_games), total=len(games), min=min_reviews, lo=lo, hi=hi))
    for col, just in [
        (_("AppID"), "right"), (_("Name"), "left"), (_("Reviews"), "right"), (_("% Pos"), "right"),
        (_("Price"), "right"), (_("Est. units (x45)"), "right"), (_("Est. gross (x30-x100)"), "right"),
    ]:
        table.add_column(col, justify=just)

    for g in hits:
        est = boxmethod.estimate(g.reviews, g.base_price)
        reviews = f"[bold]{num(g.reviews)}[/]" if g.reviews >= config.IDEAL_REVIEWS else num(g.reviews)
        color = "red" if g.rating < 40 else "yellow"
        free = g.base_price == 0
        name = f"{g.name} [dim]({_('unlisted')})[/]" if g.appid in unlisted else g.name
        table.add_row(
            str(g.appid), name, reviews, f"[{color}]{percent(g.rating)}[/]",
            "F2P" if free else fmt("${x:.2f}", x=g.base_price), num(est.units_mid),
            "n/a" if free else f"{money(est.gross_low)} - {money(est.gross_high)}",
        )
    console.print(table)
    console.print("[dim]" + _("Bold review counts = 500+ (ideal demand). Gross uses the undiscounted price, "
                              "before Steam's cut, regional pricing and discounts.") + "[/]")
    if not_games:
        console.print("[dim]" + _("Excluded non-games: {names}", names=", ".join(not_games)) + "[/]")
    console.print("[dim]" + _("Next: sr analyze <AppID>, or sr report --tag ...") + "[/]")


@app.command()
@_guarded
def analyze(
    appid: int = typer.Argument(..., min=1, help="Steam AppID (from sr discover)"),
    reviews: int = typer.Option(300, "--reviews", min=10, max=1000, help="Max negative and max positive reviews to mine"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Step 4 for one game: risk checks, complaint mining, core fantasy, design pillars."""
    http = HttpClient(use_cache=not no_cache)
    with console.status(_("Fetching SteamSpy, Steam store data and reviews...")):
        a = analyze_game(http, appid, reviews)
    if a is None:
        _print_notice(notices.Notice(
            level="error", title=_("Game not found"), message=_("SteamSpy has no data for AppID {appid}.", appid=appid),
            hint=_("Check the number on the game's Steam store page (store.steampowered.com/app/<AppID>/). "
                   "Unreleased or very new games may not be listed yet."),
        ))
        raise typer.Exit(1)
    _print_analysis(a)
    console.print()
    _print_notices(notices.for_game(a))


@app.command()
@_guarded
def report(
    tag: list[str] = TAG_OPT,
    min_reviews: int = typer.Option(config.MIN_REVIEWS, min=1, help="Demand filter"),
    rating: str = RATING_OPT,
    max_games: int = typer.Option(15, min=1, max=50, help="Analyze up to N candidates, highest review count first"),
    reviews: int = typer.Option(200, "--reviews", min=10, max=1000, help="Max negative and max positive reviews per game"),
    out: Path = typer.Option(None, "--out", "-o", help="Markdown file (default: reports/<tag>.md)"),
    with_summary: bool = typer.Option(False, "--summary", help="Also write an opportunity summary with a local LLM (Ollama)"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Steps 1-4 for a whole tag: rank games by opportunity and write a Markdown report."""
    lo, hi = _rating_range(rating)
    label = _label(tag)
    _print_notices(notices.for_filters(min_reviews, lo, hi, max_games, reviews))
    http = HttpClient(use_cache=not no_cache)
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task(_("Fetching games tagged '{tag}'...", tag=label), total=None)

        def step(message: str, done: int, total: int) -> None:
            progress.update(task, description=message[:50], completed=done, total=total)

        try:
            result = run_tag(http, tag, min_reviews, lo, hi, max_games, reviews, step)
        except UnknownTag as e:
            progress.stop()
            _unknown_tag(http, e)
    post = notices.for_tag_result(label, min_reviews, lo, hi, max_games, result)
    if not result.candidates:
        _print_notices(post)
        raise typer.Exit(1)
    analyses = result.analyses
    if with_summary:
        try:
            with console.status(_("Writing the opportunity summary with {model} (about a minute)...",
                                  model=config.LLM_MODEL)):
                result.summaries[lang()] = summary.write(label, analyses, result.market, lang())
        except LLMUnavailable as e:
            _print_notices([notices.llm_unavailable(e.missing_model)])

    text = render(
        tag=label, analyses=analyses, n_candidates=len(result.candidates), n_tag_games=result.n_tag_games,
        min_reviews=min_reviews, lo=lo, hi=hi, not_games=result.not_games, unlisted=result.unlisted,
        market=market.summary(result.market) if result.market else "",
        summary=result.summaries.get(lang()),
    )
    out = out or Path("reports") / f"{slug(label)}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    table = Table(title=_("{tag}: opportunity ranking", tag=label))
    for col, just in [("#", "right"), (_("Name"), "left"), (_("Score"), "right"), (_("Reviews"), "right"),
                      (_("% Pos"), "right"), (_("Top complaint"), "left")]:
        table.add_column(col, justify=just)
    for i, a in enumerate(rank(analyses), 1):
        o = a.opportunity
        pos = percent(a.game.rating)
        if round(o.effective_rating) != round(a.game.rating):
            pos += " " + _("({rating} adj.)", rating=percent(o.effective_rating))
        top = a.mining.categories[0] if a.mining and a.mining.categories else None
        table.add_row(
            str(i), a.game.name, f"[bold]{o.score:.0f}[/]", num(a.game.reviews), pos,
            f"{_(top.label)} ({fmt('{x:.0%}', x=top.share)})" if top else "-",
        )
    console.print(table)
    if result.market:
        console.print(f"[bold]{_('Market:')}[/] {market.summary(result.market)}")
    params = dict(tags=tag, min_reviews=min_reviews, lo=lo, hi=hi, max_games=max_games, reviews=reviews)
    runs.RunStore().save("tag", label, params, result)
    console.print(_("Report written to {path} (the run is also saved: sr runs, or Past runs in sr ui)", path=f"[bold]{out}[/]"))
    _print_notices(post)


@app.command()
@_guarded
def markets(
    min_reviews: int = typer.Option(config.MIN_REVIEWS, min=1, help="Demand filter"),
    rating: str = RATING_OPT,
    top: int = typer.Option(30, min=1, help="Max rows to show"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Rank every Steam tag by how underserved its audience is (first run ~7 min, then cached)."""
    lo, hi = _rating_range(rating)
    _print_notices(notices.for_filters(min_reviews, lo, hi, 0, 0))
    http = HttpClient(use_cache=not no_cache)
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task(_("Reading the Steam tag list"), total=None)
        result = run_markets(http, min_reviews, lo, hi,
                             lambda msg, done, total: progress.update(task, description=msg[:50], completed=done, total=total))

    table = Table(title=_("Markets: tags by underserved games (>={min} reviews, {lo:g}-{hi:g}% positive)",
                          min=min_reviews, lo=lo, hi=hi))
    for i, col in enumerate(["#", _("Tag"), _("Games"), _("With demand"), _("Underserved"),
                             _("Well served ({pct}%+)", pct=config.WELL_SERVED_RATING), _("Gap"), _("Underserved gross")]):
        table.add_column(col, justify="left" if i == 1 else "right")
    for i, r in enumerate(result.rows[:top], 1):
        m = r.stats
        table.add_row(str(i), r.tag, num(m.n_games), num(m.n_demand), f"[bold]{num(m.n_underserved)}[/]",
                      num(m.n_well_served), fmt("{x:.0%}", x=m.gap), money(m.underserved_gross))
    console.print(table)
    console.print("[dim]" + _("Gap = underserved / (underserved + well served). High gap + many underserved games = "
                              "an audience that good games don't reach yet.") + "[/]")
    if result.skipped:
        console.print("[dim]" + _("Skipped {n} tags SteamSpy can't search (search them one by one with sr discover).",
                                  n=len(result.skipped)) + "[/]")
    for tag, reason in result.failed:
        console.print(f"[yellow]{_('Could not read {tag}:', tag=tag)}[/] {reason}")
    console.print("[dim]" + _("Next: sr report --tag <Tag>") + "[/]")


@app.command("runs")
@_guarded
def list_runs(limit: int = typer.Option(20, min=1, help="Max rows to show")):
    """Saved runs from sr report and the web UI (open them in sr ui under Past runs)."""
    items = runs.RunStore().list(limit)
    if not items:
        console.print(_("No saved runs yet. Run sr report --tag ..., or search in sr ui."))
        return
    table = Table(title=_("Saved runs"))
    for i, col in enumerate([_("Date"), _("Kind"), _("Search"), _("Rows"), "ID"]):
        table.add_column(col, justify="right" if i == 3 else "left")
    for r in items:
        when = dt.datetime.fromtimestamp(r["created"]).strftime("%Y-%m-%d %H:%M")
        table.add_row(when, _("markets") if r["kind"] == "market" else _("tag"), r["label"], str(r["n"]), r["id"][:8])
    console.print(table)


def _print_analysis(a: Analysis) -> None:
    game, details = a.game, a.details
    console.rule(f"[bold]{game.name}[/] ({game.appid})")
    console.print(game.store_url)
    console.print(
        _("Reviews: {n} ({rating} positive)   Price: {price}   Owners (SteamSpy): {owners}",
          n=f"[bold]{num(game.reviews)}[/]", rating=percent(game.rating), price=fmt("${x:.2f}", x=game.base_price),
          owners=game.owners)
    )
    console.print("[dim]" + _("Review numbers: {source}", source=rating_source_text(game)) + "[/]")
    if a.has_histogram:
        console.print(_("Reviews in the last 12 months: {recent}", recent=recent_text(a)))
    if details:
        cats = ", ".join(dict.fromkeys(details.categories)) or "-"
        console.print(_("Released: {date}   Categories: {categories}", date=details.release_date, categories=cats))
    if game.tags:
        console.print(_("Top tags: {tags}", tags=", ".join(list(game.tags)[:10])))
    if game.base_price:
        est = boxmethod.estimate(game.reviews, game.base_price)
        console.print(_("Box Method: ~{units} units (x45), gross {low} - {high} (x30-x100)",
                        units=num(est.units_mid), low=money(est.gross_low), high=money(est.gross_high)))
    o = a.opportunity
    parts = _("demand {demand}, dissatisfaction {dissatisfaction} at {rating} positive, fixability {fixability}",
              demand=fmt("{x:.0%}", x=o.demand), dissatisfaction=fmt("{x:.0%}", x=o.dissatisfaction),
              rating=percent(o.effective_rating), fixability=fmt("{x:.0%}", x=o.fixability))
    if o.penalty:
        parts += _(", penalty -{points:.0f} for {names}", points=o.penalty, names=", ".join(map(risk_label, o.penalized)))
    console.print(f"[bold]{_('Opportunity score: {score:.0f}/100', score=o.score)}[/]  ({parts})")

    if a.review_error:
        console.print(f"[yellow]{_('Review texts unavailable:')}[/] {a.review_error}")
    if a.flags:
        table = Table(title=_("Risk checks"))
        table.add_column(_("Severity"))
        table.add_column(_("Check"))
        table.add_column(_("Finding"))
        for f in a.flags:
            table.add_row(f"[{SEVERITY_STYLE[f.severity]}]{severity(f.severity)}[/]", risk_label(f.code), f.text())
        console.print(table)
    else:
        console.print(f"[green]{_('No risk flags.')}[/]")
    if not a.has_histogram:
        console.print(f"[yellow]{_('No review histogram available; spike checks skipped.')}[/]")
    if a.mining:
        _print_mining(a.mining)


def _print_mining(m: MiningResult) -> None:
    if not m.n_negative:
        console.print(f"[yellow]{_('No English negative reviews to mine.')}[/]")
        return
    table = Table(title=_("What went wrong ({n} negative reviews)", n=m.n_negative))
    table.add_column(_("Complaint"))
    table.add_column(_("% of neg."), justify="right")
    table.add_column(_("Lately ({n} from last 12 mo)", n=m.n_recent_negative))
    table.add_column(_("Design pillar (do this instead)"))
    for c in m.categories:
        pillar = _(c.pillar) if c.fixable else f"[dim]{_(c.pillar)}[/]"
        table.add_row(_(c.label), fmt("{x:.0%}", x=c.share), _(c.trend) if c.trend else "-", pillar)
    console.print(table)
    console.print("[dim]" + _("Half most helpful, half newest reviews; reviews written under 2 h of play count half.") + "[/]")

    for c in m.categories[:3]:
        console.print(_("{complaint} - what players say:", complaint=f"[bold]{_(c.label)}[/]"))
        for q in c.quotes:
            console.print(f'  [dim]"{q}"[/]')

    console.print()
    console.print(
        f"[bold]{_('Great idea, bad execution?')}[/] "
        + _("{idea} of negative reviews still praise the idea or its potential.  Fixable complaints: {fix} of mentions.",
            idea=fmt("{x:.0%}", x=m.idea_praise_share), fix=fmt("{x:.0%}", x=m.fixability))
    )
    if m.core_phrases:
        phrases = ", ".join(f"{p} ({n})" for p, n in m.core_phrases)
        console.print(f"[bold]{_('Core fantasy')}[/] "
                      + _("(common phrases in {n} positive reviews): {phrases}", n=m.n_positive, phrases=phrases))
    if m.liked:
        console.print(f"[bold]{_('Players liked:')}[/] {', '.join(p for p, _n in m.liked)}")


@app.command()
def ui(
    port: int = typer.Option(8501, help="Local port"),
    open_browser: bool = typer.Option(True, "--open/--no-open", help="Open the browser"),
):
    """Open the web UI (3D opportunity map) in your browser."""
    import threading
    import webbrowser

    import uvicorn

    url = f"http://localhost:{port}"
    console.print(f"Steam Researcher UI running on {url}  (close this window or press Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.5, webbrowser.open, args=[url]).start()
    # 127.0.0.1 only: the UI is not reachable from other devices on the network
    uvicorn.run("steam_researcher.web.server:app", host="127.0.0.1", port=port, log_level="warning")


@cache_app.command("clear")
def cache_clear():
    """Delete all cached API responses."""
    console.print(f"Removed {Cache().clear()} cached entries.")


if __name__ == "__main__":
    app()
