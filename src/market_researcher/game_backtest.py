"""Game-level backtest: does anything known about an existing game X at a past date T (the score among it)
predict how new games in X's niche did afterwards?

    uv run python -m market_researcher.game_backtest --dry-run     (how many histograms a run needs)
    uv run python -m market_researcher.game_backtest               (hours the first time, then cached)

The tag-level backtest (backtest.py) found the unmet share predicts nothing and the earlier entrants' hit rate
does. The per-game score (demand x dissatisfaction) had never been tested. Design, fixed on Nov 23 2026 before
any result was seen:

- Reference games X: games with >= config.MIN_REVIEWS reviews at T (from their review histogram).
- X's niche: games sharing at least 2 of X's first 3 tags (Game.tag_ids, the store search's first 7 tags).
- Outcome: the hit rate of the niche's entrants, released in the HORIZON months after T (hit: >= 500 reviews at
  >= 80% in their first OUTCOME months, as in backtest.outcomes). Rows need >= MIN_ENTRANTS entrants.
- Measures at T (MEASURES): the current score without penalties, dissatisfaction, % positive, demand,
  demand x satisfaction, and the niche's earlier entrants' hit rate.
- Adoption: backtest.candidate() unchanged (tuning, check and recent cutoffs, niche size held fixed, fifths).
  Its bootstrap resamples by row.tag, here X's first tag: rows sharing a niche are not independent.
- Histograms only for games with >= config.MIN_REVIEWS reviews today: below that a game can neither be X nor a hit
  or sold. Entrants below it are dated by the store's release date, as pipeline.earlier_hits does; the others
  by their first month with a review, as in backtest.py.

Score candidates, added Nov 23 2026 after the first run (#12), with this rule written before they were measured:
the new score is "demand x niche's earlier hit rate (Wilson low)" if it passes backtest.candidate() and its check
rho is at most 0.02 below the plain niche rate's; else "niche's earlier hit rate (Wilson low)" under the same
rule; else the plain rate. (The 0.02 margin is the one used for Markets' Wilson ranking.)
"""

import argparse
import math
import sys
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from . import backtest, config, scoring
from .market import wilson_low
from .backtest import (CHECK_CUTOFFS, CUTOFFS, HORIZON, MIN_ENTRANTS, OUTCOME, RECENT_CUTOFFS, RECENT_WINDOW,
                       SUCCESS_RATING, SUCCESS_REVIEWS, TUNE_CUTOFFS, Outcomes, as_of, month_text, parse_month,
                       quintiles, release_month, window)
from .models import Game, HistPoint
from .peers import NICHE_SHARED, NICHE_TAGS, NicheIndex

REPORT = Path("reports") / "game-backtest.md"


@dataclass
class Entry:
    """A game as the backtest sees it: tags, release month and its success over any window."""

    appid: int
    tags: tuple[int, ...]
    hist: Sequence[HistPoint] = ()  # empty for games under config.MIN_REVIEWS today
    store_month: int | None = None  # the store's release date, for games without a histogram

    @property
    def release(self) -> int | None:
        return release_month(self.hist) if self.hist else self.store_month

    def outcome(self, months: int) -> tuple[bool, bool]:
        """(hit, sold) over its first `months` months. Games without a histogram have < 100 reviews: neither."""
        if not self.hist:
            return False, False
        up, down = window(self.hist, self.release, months)
        sold = up + down >= SUCCESS_REVIEWS
        return sold and 100 * up / (up + down) >= SUCCESS_RATING, sold


def entry(game: Game, hist: Sequence[HistPoint]) -> Entry:
    d = game.release_date
    return Entry(game.appid, tuple(game.tag_ids), hist, d.year * 12 + d.month - 1 if d else None)


def entrant_index(entries: Iterable[Entry], start: int, months: int, outcome: int) -> NicheIndex:
    """The games released in months [start, start + months), with their success over `outcome` months."""
    index = NicheIndex()
    for e in entries:
        rel = e.release
        if rel is not None and start <= rel < start + months:
            index.add(e.tags, *e.outcome(outcome))
    return index


# --- rows ---------------------------------------------------------------------------------------------------

@dataclass
class NicheMarket:
    n_demand: int  # games with >= MIN_REVIEWS reviews at T in the niche (backtest.candidate's "market size")


@dataclass
class GameRow:
    """One reference game X at cutoff T. Field names match backtest.Row where backtest.candidate reads them."""

    tag: int  # X's first tag: the bootstrap's cluster
    t: int
    appid: int
    reviews: int  # at T
    rating: float  # % positive at T
    market: NicheMarket
    after: Outcomes  # niche entrants in the window after T
    past: Outcomes = field(default_factory=Outcomes)  # niche entrants whose whole outcome window ended by T

    @property
    def usable(self) -> bool:
        return self.after.entrants >= MIN_ENTRANTS


def game_rows(entries: Sequence[Entry], t: int, horizon: int = HORIZON, outcome: int = OUTCOME) -> list[GameRow]:
    after = entrant_index(entries, t, horizon, outcome)
    past = entrant_index(entries, t - horizon - outcome, horizon, outcome)
    at_t: list[tuple[Entry, int, int]] = []
    demand = NicheIndex()
    for e in entries:
        if not e.hist or len(e.tags) < 2:
            continue
        up, down = as_of(e.hist, t)
        if up + down >= config.MIN_REVIEWS:
            at_t.append((e, up, down))
            demand.add(e.tags)
    rows = []
    for e, up, down in at_t:
        tags = e.tags[:NICHE_TAGS]
        rows.append(GameRow(tag=e.tags[0], t=t, appid=e.appid, reviews=up + down, rating=100 * up / (up + down),
                            market=NicheMarket(demand.niche(tags).entrants),
                            after=after.niche(tags), past=past.niche(tags)))
    return rows


# --- measures (each known at T), fixed before the results were seen ------------------------------------------

# The score's formula until #12: a weighted geometric mean of demand and dissatisfaction, which from #6 on counted
# dissatisfaction rescaled to [OLD_FLOOR, 1].
OLD_WEIGHTS = {"demand": 0.40, "dissatisfaction": 0.35}
OLD_FLOOR = 0.25


def _geo(demand: float, other: float) -> float:
    """The old score's weighted geometric mean (OLD_WEIGHTS) of demand and one other part."""
    w = OLD_WEIGHTS
    if demand <= 0 or other <= 0:
        return 0.0
    return 100 * math.exp((w["demand"] * math.log(demand) + w["dissatisfaction"] * math.log(other)) / sum(w.values()))


def satisfaction(rating: float) -> float:
    """0 at MIN_RATING (5%), 1 at 100%: the mirror of scoring.dissatisfaction, without its 70% cap."""
    return max(0.0, min(1.0, (rating - config.MIN_RATING) / (100 - config.MIN_RATING)))


def _niche_low(r: GameRow) -> float | None:
    return max(0.0, wilson_low(r.past.hits, r.past.entrants)) if r.past.entrants >= MIN_ENTRANTS else None  # float error: -1e-17


MEASURES: dict[str, Callable[[GameRow], float | None]] = {
    # The score changed before this ran (#6, Nov 23 2026: dissatisfaction floor), so both formulas are measured.
    "score Nov 23 2026 (soft floor, no penalties)": lambda r: _geo(
        scoring.demand(r.reviews), OLD_FLOOR + (1 - OLD_FLOOR) * scoring.dissatisfaction(r.rating)),
    "score before Nov 23 2026 (no floor, no penalties)": lambda r: _geo(scoring.demand(r.reviews),
                                                                         scoring.dissatisfaction(r.rating)),
    "dissatisfaction": lambda r: scoring.dissatisfaction(r.rating),
    "% positive": lambda r: r.rating,
    "demand": lambda r: scoring.demand(r.reviews),
    "demand x satisfaction": lambda r: _geo(scoring.demand(r.reviews), satisfaction(r.rating)),
    "niche's earlier entrants' hit rate": lambda r: r.past.hit_rate if r.past.entrants >= MIN_ENTRANTS else None,
    # Score candidates (#12, see the module docstring for the rule).
    "niche's earlier hit rate (Wilson low)": lambda r: _niche_low(r),
    "demand x niche's earlier hit rate (Wilson low)": lambda r: (
        None if _niche_low(r) is None else math.sqrt(scoring.demand(r.reviews) * _niche_low(r))),
}


# --- report -------------------------------------------------------------------------------------------------

def render(rows: Sequence[GameRow], recent: Sequence[GameRow], n_games: int, n_hists: int) -> str:
    used = [r for r in rows if r.usable]
    recent_used = [r for r in recent if r.usable]
    lines = [
        "# Game-level backtest: does what we know about a game predict success in its niche?",
        "",
        f"Reference games X: >= {config.MIN_REVIEWS} reviews at T. X's niche: games sharing >= {NICHE_SHARED} of X's "
        f"first {NICHE_TAGS} tags. Outcome: hit rate of the niche's games released in the {HORIZON} months after T "
        f"(hit: >= {SUCCESS_REVIEWS} reviews at >= {SUCCESS_RATING:.0f}% in their first {OUTCOME} months). "
        f"Rows need >= {MIN_ENTRANTS} entrants.",
        f"Data: {n_games:,} rated games, {n_hists:,} review histograms (games with >= {config.MIN_REVIEWS} reviews today).",
        f"Usable rows (X x T): {len(used):,} from {len({r.appid for r in used}):,} games; recent: {len(recent_used):,}.",
        "",
        "## Measures (fixed before the results were seen)",
        "",
        f"Each vs the niche's hit rate, Spearman within each T. Tuned on {', '.join(TUNE_CUTOFFS)}; checked once on "
        f"{', '.join(CHECK_CUTOFFS)}; recent {', '.join(RECENT_CUTOFFS)} with {RECENT_WINDOW}-month windows. Adopted only "
        "if backtest.candidate() passes: interval excludes 0 on tuning, check and recent, the sign holds with the "
        f"niche's size held fixed, and the favored fifth's hit rate is >= {backtest.MIN_FIFTH_RATIO} x the other end's. "
        "Intervals resample X's first tag.",
        "",
        "| Measure | Tuning rho (95%) | Check rho (95%) | Check, size fixed | Check fifths: favored vs other end | Recent rho (95%) | Adopted |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, measure in MEASURES.items():
        c = backtest.candidate(name, measure, used, recent_used)
        fixed = "-" if c.check_fixed != c.check_fixed else f"{c.check_fixed:+.2f}"
        lines.append(f"| {c.name} | {c.tune[0]:+.2f} ({c.tune[1]:+.2f} to {c.tune[2]:+.2f}) | "
                     f"{c.check[0]:+.2f} ({c.check[1]:+.2f} to {c.check[2]:+.2f}) | {fixed} | "
                     f"{c.fifths[0]:.1%} vs {c.fifths[1]:.1%} | {c.recent[0]:+.2f} ({c.recent[1]:+.2f} to {c.recent[2]:+.2f}) | "
                     f"{'yes' if c.passed else 'no'} |")
    for name, measure in MEASURES.items():
        kept = [r for r in used if month_text(r.t) in CHECK_CUTOFFS and measure(r) is not None]
        lines += ["", f"### Check cutoffs by {name} (fifths within each T, pooled; 1 = lowest)", "",
                  "| Fifth | Rows | Entrants | Hit rate | Sold rate |", "|---|---|---|---|---|"]
        for i, (k, n, hits, sold) in enumerate(quintiles(kept, lambda r, m=measure: m(r)), 1):
            lines.append(f"| {i} | {k:,} | {n:,} | {hits / n if n else 0:.1%} | {sold / n if n else 0:.1%} |")
    lines += [
        "",
        "## Known biases",
        "",
        "- The tag-level backtest's: survivorship, today's tags, review bombs in the histogram, games with < 10 "
        "reviews missing, release month = first review month for games with a histogram.",
        f"- Entrants under {config.MIN_REVIEWS} reviews today are dated by the store's release date (the 1.0 date for games "
        "that left Early Access).",
        "- Niches overlap: one entrant counts toward many X, so rows are far from independent; the intervals resample "
        "X's first tag to allow for that.",
        "- Penalties (risk flags) are left out of the score: they need review texts and store data from T.",
    ]
    return "\n".join(lines) + "\n"


def main() -> None:
    from .http import HttpClient
    from .sources import steam_search, steam_store

    ap = argparse.ArgumentParser(description="Game-level backtest of the score and other measures.")
    ap.add_argument("--cutoffs", nargs="+", default=CUTOFFS, help="cutoff months, YYYY-MM")
    ap.add_argument("--tags", action="append", default=[], help="only games with this tag (repeatable; a quick look)")
    ap.add_argument("--dry-run", action="store_true", help="only count the histograms a run needs")
    ap.add_argument("--out", type=Path, default=REPORT)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    http = HttpClient()

    games = steam_search.games_by_tags(http, [])  # every rated game, ~36 min the first time
    if args.tags:
        ids = {name.casefold(): i for name, i in steam_store.tag_ids(http).items()}
        wanted = {ids[t.casefold()] for t in args.tags}
        games = [g for g in games if wanted & set(g.tag_ids)]
    fetch = sorted(g.appid for g in games if g.positive + g.negative >= config.MIN_REVIEWS)
    print(f"{len(games):,} games, {len(fetch):,} histograms to fetch (~{len(fetch) * 1.5 / 3600:.1f} h if none is cached)",
          flush=True)
    if args.dry_run:
        return
    hists: dict[int, list[HistPoint]] = {}
    for i, appid in enumerate(fetch, 1):
        try:
            hists[appid] = steam_store.review_histogram(http, appid, ttl=backtest.HIST_TTL)
        except Exception as e:
            print(f"histogram {appid}: {e}", flush=True)
            hists[appid] = []
        if i % 500 == 0 or i == len(fetch):
            print(f"histograms {i:,}/{len(fetch):,}", flush=True)
    # A game whose histogram failed is left out: its success can't be told.
    entries = [entry(g, hists.get(g.appid, [])) for g in games if g.appid not in hists or hists[g.appid]]
    rows = [r for t in args.cutoffs for r in game_rows(entries, parse_month(t))]
    recent = ([r for t in RECENT_CUTOFFS for r in game_rows(entries, parse_month(t), RECENT_WINDOW, RECENT_WINDOW)]
              if args.cutoffs == CUTOFFS else [])
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows, recent, len(games), sum(1 for h in hists.values() if h)), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
