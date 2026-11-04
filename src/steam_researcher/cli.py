import functools
import os
from pathlib import Path

import click
import typer
from rich.console import Console
from rich.progress import Progress
from rich.table import Table

from . import boxmethod, config, notices
from .cache import Cache
from .discover import filter_candidates, parse_rating_range
from .http import HttpClient
from .models import Analysis, MiningResult
from .pipeline import TagResult, analyze_game, run_tag, verify_games
from .report import money, rank, render, slug
from .sources import steamspy

app = typer.Typer(help="Find underserved Steam audiences (CodeMonkey's method).", no_args_is_help=True)
cache_app = typer.Typer(help="Manage the local cache.")
app.add_typer(cache_app, name="cache")
console = Console()

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
        except (typer.Exit, click.exceptions.Exit, click.exceptions.ClickException, click.exceptions.Abort,
                KeyboardInterrupt):
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


def _tag_games(http: HttpClient, tag: str):
    with console.status(f"Fetching games tagged {tag!r} from SteamSpy..."):
        games = steamspy.games_by_tag(http, tag)
    if not games:
        _print_notice(notices.unknown_tag(tag))
        raise typer.Exit(1)
    return games


RATING_OPT = typer.Option(
    f"{config.MIN_RATING:g}-{config.MAX_RATING:g}", "--rating", help="Allowed % positive range, LO-HI"
)
NO_CACHE_OPT = typer.Option(False, "--no-cache", help="Bypass the cache")


@app.command()
@_guarded
def discover(
    tag: str = typer.Option(..., "--tag", "-t", help='Steam tag, e.g. "Job Simulator"'),
    min_reviews: int = typer.Option(config.MIN_REVIEWS, min=1, help="Demand filter"),
    rating: str = RATING_OPT,
    top: int = typer.Option(30, min=1, help="Max rows to show"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Steps 1-3: list games in a tag with proven demand but weak satisfaction."""
    lo, hi = _rating_range(rating)
    _print_notices(notices.for_filters(min_reviews, lo, hi, 0, 0))
    http = HttpClient(use_cache=not no_cache)
    games = _tag_games(http, tag)
    candidates = filter_candidates(games, min_reviews, lo, hi)
    if not candidates:
        empty = TagResult(n_tag_games=len(games), candidates=[],
                          n_enough_reviews=sum(g.reviews >= min_reviews for g in games))
        _print_notices(notices.for_tag_result(tag, min_reviews, lo, hi, top, empty))
        raise typer.Exit(1)

    with console.status("Checking store type (games only)...") as status:
        hits, not_games, unlisted = verify_games(
            http, candidates, top, lambda g: status.update(f"Checking store type: {g.name}")
        )

    table = Table(
        title=f"{tag}: {len(candidates) - len(not_games)} of {len(games)} games with "
        f">={min_reviews} reviews and {lo:g}-{hi:g}% positive"
    )
    for col, just in [
        ("AppID", "right"), ("Name", "left"), ("Reviews", "right"), ("% Pos", "right"),
        ("Price", "right"), ("Est. units (x45)", "right"), ("Est. gross (x30-x100)", "right"),
    ]:
        table.add_column(col, justify=just)

    for g in hits:
        est = boxmethod.estimate(g.reviews, g.base_price)
        reviews = f"[bold]{g.reviews:,}[/]" if g.reviews >= config.IDEAL_REVIEWS else f"{g.reviews:,}"
        color = "red" if g.rating < 40 else "yellow"
        free = g.base_price == 0
        name = f"{g.name} [dim](unlisted)[/]" if g.appid in unlisted else g.name
        table.add_row(
            str(g.appid), name, reviews, f"[{color}]{g.rating:.0f}%[/]",
            "F2P" if free else f"${g.base_price:.2f}", f"{est.units_mid:,}",
            "n/a" if free else f"{money(est.gross_low)} - {money(est.gross_high)}",
        )
    console.print(table)
    console.print(
        "[dim]Bold review counts = 500+ (ideal demand). Gross uses the undiscounted price, "
        "before Steam's cut, regional pricing and discounts.[/]"
    )
    if not_games:
        console.print(f"[dim]Excluded non-games: {', '.join(not_games)}[/]")
    console.print("[dim]Next: sr analyze <AppID>, or sr report --tag ...[/]")


@app.command()
@_guarded
def analyze(
    appid: int = typer.Argument(..., min=1, help="Steam AppID (from sr discover)"),
    reviews: int = typer.Option(300, "--reviews", min=10, max=1000, help="Max negative and max positive reviews to mine"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Step 4 for one game: risk checks, complaint mining, core fantasy, design pillars."""
    http = HttpClient(use_cache=not no_cache)
    with console.status("Fetching SteamSpy, Steam store data and reviews..."):
        a = analyze_game(http, appid, reviews)
    if a is None:
        _print_notice(notices.Notice(
            level="error", title="Game not found", message=f"SteamSpy has no data for AppID {appid}.",
            hint="Check the number on the game's Steam store page (store.steampowered.com/app/<AppID>/).",
        ))
        raise typer.Exit(1)
    _print_analysis(a)
    console.print()
    _print_notices(notices.for_game(a))


@app.command()
@_guarded
def report(
    tag: str = typer.Option(..., "--tag", "-t", help='Steam tag, e.g. "Job Simulator"'),
    min_reviews: int = typer.Option(config.MIN_REVIEWS, min=1, help="Demand filter"),
    rating: str = RATING_OPT,
    max_games: int = typer.Option(15, min=1, max=50, help="Analyze up to N candidates, highest review count first"),
    reviews: int = typer.Option(200, "--reviews", min=10, max=1000, help="Max negative and max positive reviews per game"),
    out: Path = typer.Option(None, "--out", "-o", help="Markdown file (default: reports/<tag>.md)"),
    no_cache: bool = NO_CACHE_OPT,
):
    """Steps 1-4 for a whole tag: rank games by opportunity and write a Markdown report."""
    lo, hi = _rating_range(rating)
    _print_notices(notices.for_filters(min_reviews, lo, hi, max_games, reviews))
    http = HttpClient(use_cache=not no_cache)
    with Progress(console=console, transient=True) as progress:
        task = progress.add_task(f"Fetching games tagged {tag!r}", total=None)

        def step(message: str, done: int, total: int) -> None:
            progress.update(task, description=message[:50], completed=done, total=total)

        result = run_tag(http, tag, min_reviews, lo, hi, max_games, reviews, step)
    if result is None:
        _print_notice(notices.unknown_tag(tag))
        raise typer.Exit(1)
    post = notices.for_tag_result(tag, min_reviews, lo, hi, max_games, result)
    if not result.candidates:
        _print_notices(post)
        raise typer.Exit(1)
    analyses = result.analyses

    text = render(
        tag=tag, analyses=analyses, n_candidates=len(result.candidates), n_tag_games=result.n_tag_games,
        min_reviews=min_reviews, lo=lo, hi=hi, not_games=result.not_games, unlisted=result.unlisted,
    )
    out = out or Path("reports") / f"{slug(tag)}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")

    table = Table(title=f"{tag}: opportunity ranking")
    for col, just in [("#", "right"), ("Name", "left"), ("Score", "right"), ("Reviews", "right"),
                      ("% Pos", "right"), ("Top complaint", "left")]:
        table.add_column(col, justify=just)
    for i, a in enumerate(rank(analyses), 1):
        o = a.opportunity
        pos = f"{a.game.rating:.0f}%"
        if round(o.effective_rating) != round(a.game.rating):
            pos += f" ({o.effective_rating:.0f}% adj.)"
        top = a.mining.categories[0] if a.mining and a.mining.categories else None
        table.add_row(
            str(i), a.game.name, f"[bold]{o.score:.0f}[/]", f"{a.game.reviews:,}", pos,
            f"{top.label} ({top.share:.0%})" if top else "-",
        )
    console.print(table)
    console.print(f"Report written to [bold]{out}[/]")
    _print_notices(post)


def _print_analysis(a: Analysis) -> None:
    game, details = a.game, a.details
    console.rule(f"[bold]{game.name}[/] ({game.appid})")
    console.print(game.store_url)
    console.print(
        f"Reviews: [bold]{game.reviews:,}[/] ({game.rating:.0f}% positive)   "
        f"Price: ${game.base_price:.2f}   Owners (SteamSpy): {game.owners}"
    )
    if details:
        cats = ", ".join(dict.fromkeys(details.categories)) or "-"
        console.print(f"Released: {details.release_date}   Categories: {cats}")
    if game.tags:
        console.print(f"Top tags: {', '.join(list(game.tags)[:10])}")
    if game.base_price:
        est = boxmethod.estimate(game.reviews, game.base_price)
        console.print(
            f"Box Method: ~{est.units_mid:,} units (x45), gross "
            f"{money(est.gross_low)} - {money(est.gross_high)} (x30-x100)"
        )
    o = a.opportunity
    console.print(
        f"[bold]Opportunity score: {o.score:.0f}/100[/]  (demand {o.demand:.0%}, "
        f"dissatisfaction {o.dissatisfaction:.0%} at {o.effective_rating:.0f}% positive, "
        f"fixability {o.fixability:.0%}"
        + (f", penalty -{o.penalty:.0f} for {', '.join(o.penalized)}" if o.penalty else "")
        + ")"
    )

    if a.review_error:
        console.print(f"[yellow]Review texts unavailable:[/] {a.review_error}")
    if a.flags:
        table = Table(title="Risk checks")
        table.add_column("Severity")
        table.add_column("Check")
        table.add_column("Finding")
        for f in a.flags:
            table.add_row(f"[{SEVERITY_STYLE[f.severity]}]{f.severity}[/]", f.code, f.message)
        console.print(table)
    else:
        console.print("[green]No risk flags.[/]")
    if not a.has_histogram:
        console.print("[yellow]No review histogram available; spike checks skipped.[/]")
    if a.mining:
        _print_mining(a.mining)


def _print_mining(m: MiningResult) -> None:
    if not m.n_negative:
        console.print("[yellow]No English negative reviews to mine.[/]")
        return
    table = Table(title=f"What went wrong ({m.n_negative} negative reviews)")
    table.add_column("Complaint")
    table.add_column("% of neg.", justify="right")
    table.add_column("Design pillar (do this instead)")
    for c in m.categories:
        pillar = c.pillar if c.fixable else f"[dim]{c.pillar}[/]"
        table.add_row(c.label, f"{c.share:.0%}", pillar)
    console.print(table)

    for c in m.categories[:3]:
        console.print(f"[bold]{c.label}[/] - what players say:")
        for q in c.quotes:
            console.print(f'  [dim]"{q}"[/]')

    console.print()
    console.print(
        f"[bold]Great idea, bad execution?[/] {m.idea_praise_share:.0%} of negative reviews still praise "
        f"the idea or its potential.  Fixable complaints: {m.fixability:.0%} of mentions."
    )
    if m.core_phrases:
        phrases = ", ".join(f"{p} ({n})" for p, n in m.core_phrases)
        console.print(f"[bold]Core fantasy[/] (common phrases in {m.n_positive} positive reviews): {phrases}")
    if m.liked:
        console.print(f"[bold]Players liked:[/] {', '.join(p for p, _ in m.liked)}")


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
