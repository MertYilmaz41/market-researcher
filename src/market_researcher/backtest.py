"""Backtest: did tags the tool would have called underserved at a past date T later reward new games?

    uv run python -m market_researcher.backtest --tags "Job Simulator" --tags "Colony Sim"
    uv run python -m market_researcher.backtest --all --dry-run     (how many histograms a full run needs)
    uv run python -m market_researcher.backtest --all               (hours the first time, then cached)

Each game's monthly review histogram gives its review count and % positive at any month, and its
release month (the first month with reviews; Steam reviews start in Oct 2010, so older games look
released then). For every tag and cutoff T this rebuilds the tag's market (market.market_stats, as the
app computes it today) from the games as they were at T, then follows the games that came out in the
HORIZON months after T: a game succeeds if, in its first OUTCOME months, it got >= SUCCESS_REVIEWS
reviews at >= SUCCESS_RATING % positive ("hit"), or just >= SUCCESS_REVIEWS reviews ("sold").

The claim under test: a higher unmet share (gap) at T means later games in that tag succeed more often.

Tuning market settings on this (rating ranges, market_rank, new market measures): use only the 2019-01 and
2020-01 cutoffs, and adopt a change only if it also beats the current setting on 2021-01 and 2022-01, which
are never tuned on. Try a few candidates written down in advance, and record each result in CLAUDE.md,
including the rejected ones. These rules were fixed before the full run's results were seen (Nov 2026).
"""

import argparse
import datetime as dt
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from statistics import correlation, fmean

from . import config
from .market import MarketStats, market_stats
from .models import Game, HistPoint

CUTOFFS = ["2019-01", "2020-01", "2021-01", "2022-01"]
HORIZON = 24  # months after T in which a game counts as an entrant
OUTCOME = 24  # months after release over which an entrant's success is measured
SUCCESS_REVIEWS = config.IDEAL_REVIEWS  # 500
SUCCESS_RATING = 80.0
MIN_HIST_REVIEWS = 10  # games with fewer reviews today aren't fetched: they can't have succeeded
MIN_ENTRANTS = 10  # (tag, T) rows with fewer entrants are too noisy to rank
MIN_RATED = 5  # ...and rows whose gap rests on fewer underserved + well-served games
HIST_TTL = 30 * 24 * 3600  # past months don't change; a long TTL keeps reruns fast
REPORT = Path("reports") / "backtest.md"


def month(ts: int) -> int:
    d = dt.datetime.fromtimestamp(ts, dt.UTC)
    return d.year * 12 + d.month - 1


def parse_month(text: str) -> int:
    year, mon = text.split("-")
    return int(year) * 12 + int(mon) - 1


def month_text(m: int) -> str:
    return f"{m // 12}-{m % 12 + 1:02d}"


def _counts(hist: Sequence[HistPoint], keep: Callable[[int], bool]) -> tuple[int, int]:
    pts = [p for p in hist if keep(month(p.date))]
    return sum(p.up for p in pts), sum(p.down for p in pts)


def as_of(hist: Sequence[HistPoint], t: int) -> tuple[int, int]:
    """(up, down) from all months before month t."""
    return _counts(hist, lambda m: m < t)


def window(hist: Sequence[HistPoint], start: int, months: int) -> tuple[int, int]:
    """(up, down) in months [start, start + months)."""
    return _counts(hist, lambda m: start <= m < start + months)


def release_month(hist: Sequence[HistPoint]) -> int | None:
    return next((month(p.date) for p in hist if p.total > 0), None)


def game_at(game: Game, hist: Sequence[HistPoint], t: int) -> Game | None:
    """The game as it looked at month t (None if it had no reviews yet)."""
    up, down = as_of(hist, t)
    if up + down == 0:
        return None
    return game.model_copy(update={"positive": up, "negative": down, "offtopic_reviews": 0})


@dataclass
class Outcomes:
    entrants: int = 0
    hits: int = 0  # >= SUCCESS_REVIEWS reviews at >= SUCCESS_RATING %
    sold: int = 0  # >= SUCCESS_REVIEWS reviews, any rating

    @property
    def hit_rate(self) -> float:
        return self.hits / self.entrants if self.entrants else 0.0

    @property
    def sold_rate(self) -> float:
        return self.sold / self.entrants if self.entrants else 0.0


def outcomes(hists: Sequence[Sequence[HistPoint]], start: int, months: int = HORIZON, outcome: int = OUTCOME) -> Outcomes:
    """Success of the games released in months [start, start + months), each over its first `outcome` months."""
    out = Outcomes()
    for hist in hists:
        rel = release_month(hist)
        if rel is None or not start <= rel < start + months:
            continue
        up, down = window(hist, rel, outcome)
        out.entrants += 1
        if up + down >= SUCCESS_REVIEWS:
            out.sold += 1
            if 100 * up / (up + down) >= SUCCESS_RATING:
                out.hits += 1
    return out


@dataclass
class Row:
    tag: str
    t: int
    market: MarketStats  # the tag at T
    after: Outcomes  # entrants in the HORIZON months after T
    before: Outcomes  # entrants in the HORIZON months before T (the tag's base rate)
    # Entrants released HORIZON + OUTCOME to OUTCOME months before T: their whole OUTCOME window ends
    # by T, so their success was known at T (unlike `before`, whose outcomes run past T).
    past: Outcomes = field(default_factory=Outcomes)

    @property
    def usable(self) -> bool:
        return self.after.entrants >= MIN_ENTRANTS and self.market.n_underserved + self.market.n_well_served >= MIN_RATED


def tag_row(tag: str, games: Sequence[tuple[Game, Sequence[HistPoint]]], t: int,
            horizon: int = HORIZON, outcome: int = OUTCOME) -> Row:
    then = [past for g, h in games if (past := game_at(g, h, t)) is not None]
    hists = [h for _, h in games]
    return Row(
        tag=tag,
        t=t,
        market=market_stats(then, config.MIN_REVIEWS, config.MIN_RATING, config.MAX_RATING),
        after=outcomes(hists, t, horizon, outcome),
        before=outcomes(hists, t - horizon, horizon, outcome),
        past=outcomes(hists, t - horizon - outcome, horizon, outcome),
    )


# --- statistics (no numpy: Spearman via statistics.correlation, CIs by resampling tags) ---------------


def spearman(x: Sequence[float], y: Sequence[float]) -> float:
    if len(x) < 3 or len(set(x)) < 2 or len(set(y)) < 2:
        return float("nan")
    return correlation(x, y, method="ranked")


def partial_spearman(x: Sequence[float], y: Sequence[float], z: Sequence[float]) -> float:
    """Rank correlation of x and y with z held fixed."""
    rxy, rxz, ryz = spearman(x, y), spearman(x, z), spearman(y, z)
    denom = ((1 - rxz**2) * (1 - ryz**2)) ** 0.5
    return (rxy - rxz * ryz) / denom if denom else float("nan")


def bootstrap(rows: Sequence[Row], stat: Callable[[Sequence[Row]], float], n: int = 2000) -> tuple[float, float]:
    """95% interval, resampling whole tags: one tag's rows at different T are not independent."""
    by_tag: dict[str, list[Row]] = {}
    for r in rows:
        by_tag.setdefault(r.tag, []).append(r)
    tags = list(by_tag)
    rng = random.Random(0)
    vals = []
    for _ in range(n):
        sample = [r for tag in rng.choices(tags, k=len(tags)) for r in by_tag[tag]]
        v = stat(sample)
        if v == v:  # skip NaN
            vals.append(v)
    if not vals:
        return float("nan"), float("nan")
    vals.sort()
    return vals[int(0.025 * len(vals))], vals[int(0.975 * len(vals)) - 1]


def _gap(rows):
    return [r.market.gap for r in rows]


def _by_cutoff(rows: Sequence[Row]) -> dict[int, list[Row]]:
    out: dict[int, list[Row]] = {}
    for r in rows:
        out.setdefault(r.t, []).append(r)
    return out


def per_cutoff(stat: Callable[[Sequence[Row]], float]) -> Callable[[Sequence[Row]], float]:
    """Mean of the statistic within each cutoff. Success rates fall year by year (more games every
    year), so pooling rows from different T would mix that trend into the comparison."""
    def mean(rows: Sequence[Row]) -> float:
        vals = [v for part in _by_cutoff(rows).values() if (v := stat(part)) == v]
        return fmean(vals) if vals else float("nan")
    return mean


STATS: dict[str, Callable[[Sequence[Row]], float]] = {
    "gap vs hit rate": lambda rs: spearman(_gap(rs), [r.after.hit_rate for r in rs]),
    "gap vs sold rate": lambda rs: spearman(_gap(rs), [r.after.sold_rate for r in rs]),
    "market size vs hit rate": lambda rs: spearman([r.market.n_demand for r in rs], [r.after.hit_rate for r in rs]),
    "gap vs hit rate, market size held fixed": lambda rs: partial_spearman(
        _gap(rs), [r.after.hit_rate for r in rs], [r.market.n_demand for r in rs]),
    "gap vs change in hit rate (after - before)": lambda rs: spearman(
        _gap(rs), [r.after.hit_rate - r.before.hit_rate for r in rs]),
}


def quintiles(rows: Sequence[Row], key: Callable[[Row], float] = lambda r: r.market.gap) -> list[tuple[int, int, int, int]]:
    """Within each cutoff, rows sorted by key (the gap) and cut into fifths; fifth i of every cutoff
    pooled: (rows, entrants, hits, sold) per fifth, lowest key first."""
    out = [[0, 0, 0, 0] for _ in range(5)]
    for part in _by_cutoff(rows).values():
        ordered = sorted(part, key=key)
        for j, r in enumerate(ordered):
            q = out[j * 5 // len(ordered)]
            q[0] += 1
            q[1] += r.after.entrants
            q[2] += r.after.hits
            q[3] += r.after.sold
    return [tuple(q) for q in out if q[0]]


# Pass criteria, fixed before the full run's results were seen (Nov 2026). All must hold.
MIN_FIFTH_RATIO = 1.25  # top fifth's hit rate >= 1.25 x the bottom fifth's: big enough to matter


def verdict(rows: Sequence[Row]) -> tuple[str, list[tuple[str, bool]]]:
    """("holds" | "does not hold" | "not enough data", [(check, passed)]) for the usable rows."""
    main, partial = per_cutoff(STATS["gap vs hit rate"]), per_cutoff(STATS["gap vs hit rate, market size held fixed"])
    rho, (lo, _) = main(rows), bootstrap(rows, main)
    rho_fixed = partial(rows)
    fifths = quintiles(rows)
    if rho != rho or lo != lo or rho_fixed != rho_fixed or len(fifths) < 5:
        return "not enough data", []
    bottom = fifths[0][2] / fifths[0][1] if fifths[0][1] else 0.0
    top = fifths[-1][2] / fifths[-1][1] if fifths[-1][1] else 0.0
    checks = [
        (f"gap vs hit rate: rho > 0 (rho {rho:+.2f})", rho > 0),
        (f"its 95% interval excludes 0 (lower end {lo:+.2f})", lo > 0),
        (f"still > 0 with market size held fixed (rho {rho_fixed:+.2f})", rho_fixed > 0),
        (f"top fifth's hit rate >= {MIN_FIFTH_RATIO} x the bottom fifth's ({top:.1%} vs {bottom:.1%})",
         top >= MIN_FIFTH_RATIO * bottom and top > 0),
    ]
    return ("holds" if all(ok for _, ok in checks) else "does not hold"), checks


# --- other market measures --------------------------------------------------------------------------
# Written down on Nov 7 2026, after the full run showed the gap fails and before any of these was
# measured per cutoff (only "market size vs hit rate", pooled over all four cutoffs, had been seen).
# Each is known at T. Tuned on TUNE_CUTOFFS, checked once on CHECK_CUTOFFS.
TUNE_CUTOFFS = ("2019-01", "2020-01")
CHECK_CUTOFFS = ("2021-01", "2022-01")
# Recent check (fixed Nov 7 2026, before any result for it was seen): with 24 + 24 month windows, 2022-01
# is the last cutoff whose outcomes are complete. With 12-month windows (entrants in the 12 months after T,
# success within their first 12 months, the same 500 reviews / 80%) T can be 2023-01 and 2024-01, so
# these show whether a link still holds on today's busier Steam. Never tuned on. A candidate is adopted
# only if it also holds here: the tuning sign, and its 95% interval excludes 0.
RECENT_CUTOFFS = ("2023-01", "2024-01")
RECENT_WINDOW = 12
CANDIDATES: dict[str, Callable[[Row], float | None]] = {
    "games with demand (market size)": lambda r: r.market.n_demand,
    "underserved games": lambda r: r.market.n_underserved,
    "well-served games": lambda r: r.market.n_well_served,
    "earlier entrants' hit rate (released 48-24 months before T)":
        lambda r: r.past.hit_rate if r.past.entrants >= MIN_ENTRANTS else None,
    "releases in the 24 months before T": lambda r: r.before.entrants,
}


@dataclass
class Candidate:
    name: str
    tune: tuple[float, float, float]  # rho, 95% interval, on the tuning cutoffs
    check: tuple[float, float, float]  # the same on the check cutoffs
    check_fixed: float  # check rho with market size held fixed (nan for market size itself)
    fifths: tuple[float, float]  # check: hit rate of the fifth the sign favors, and of the other end
    recent: tuple[float, float, float]  # rho and 95% interval on the recent cutoffs (12-month windows)
    passed: bool


def _rho_ci(rows: Sequence[Row], key: Callable[[Row], float]) -> tuple[float, float, float]:
    stat = per_cutoff(lambda rs: spearman([key(r) for r in rs], [r.after.hit_rate for r in rs]))
    return (stat(rows), *bootstrap(rows, stat))


def candidate(name: str, measure: Callable[[Row], float | None], rows: Sequence[Row],
              recent_rows: Sequence[Row] = ()) -> Candidate:
    """Adopted only if: on the tuning cutoffs the interval excludes 0; on the check cutoffs the rho has
    the same sign, its interval excludes 0, it keeps that sign with market size held fixed (except
    market size itself), and the favored fifth's hit rate is >= MIN_FIFTH_RATIO x the other end's; and on
    the recent cutoffs (recent_rows) the sign holds and its interval excludes 0."""
    rows = [r for r in rows if measure(r) is not None]
    recent_rows = [r for r in recent_rows if measure(r) is not None]
    key = lambda r: measure(r)  # noqa: E731
    tune = _rho_ci([r for r in rows if month_text(r.t) in TUNE_CUTOFFS], key)
    check_rows = [r for r in rows if month_text(r.t) in CHECK_CUTOFFS]
    check = _rho_ci(check_rows, key)
    size = name.startswith("games with demand")
    fixed = float("nan") if size else per_cutoff(lambda rs: partial_spearman(
        [key(r) for r in rs], [r.after.hit_rate for r in rs], [r.market.n_demand for r in rs]))(check_rows)
    sign = 1 if tune[0] >= 0 else -1
    q = quintiles(check_rows, key)
    rates = [hits / n if n else 0.0 for _, n, hits, _ in q] or [0.0]
    best, worst = (rates[-1], rates[0]) if sign > 0 else (rates[0], rates[-1])
    recent = _rho_ci(recent_rows, key) if recent_rows else (float("nan"),) * 3
    passed = (sign * recent[1] > 0 and sign * recent[2] > 0
              and sign * tune[1] > 0 and sign * tune[2] > 0 and sign * check[0] > 0 and sign * check[1] > 0
              and sign * check[2] > 0 and (size or sign * fixed > 0) and len(q) == 5
              and best >= MIN_FIFTH_RATIO * worst and best > 0)
    return Candidate(name, tune, check, fixed, (best, worst), recent, passed)


def render_candidates(rows: Sequence[Row], recent_rows: Sequence[Row] = ()) -> list[str]:
    lines = ["", "## Other market measures (candidates fixed in advance)", "",
             f"Each vs the hit rate, Spearman within each T. Tuned on {', '.join(TUNE_CUTOFFS)}; checked once on "
             f"{', '.join(CHECK_CUTOFFS)}. Adopted only if the tuning interval excludes 0 and, on the check cutoffs, "
             f"the sign holds, its interval excludes 0, it holds with market size fixed, and the favored fifth's "
             f"hit rate is >= {MIN_FIFTH_RATIO} x the other end's, and on the recent cutoffs "
             f"({', '.join(RECENT_CUTOFFS)}, {RECENT_WINDOW}-month windows) the sign holds and its interval excludes 0. "
             "Market size vs hit rate pooled over all four cutoffs (+0.28) had been seen before these were written down.", "",
             "| Measure | Tuning rho (95%) | Check rho (95%) | Check, size fixed | Check fifths: favored vs other end | Recent rho (95%) | Adopted |",
             "|---|---|---|---|---|---|---|"]
    for name, measure in CANDIDATES.items():
        c = candidate(name, measure, rows, recent_rows)
        fixed = "-" if c.check_fixed != c.check_fixed else f"{c.check_fixed:+.2f}"
        lines.append(f"| {c.name} | {c.tune[0]:+.2f} ({c.tune[1]:+.2f} to {c.tune[2]:+.2f}) | "
                     f"{c.check[0]:+.2f} ({c.check[1]:+.2f} to {c.check[2]:+.2f}) | {fixed} | "
                     f"{c.fifths[0]:.1%} vs {c.fifths[1]:.1%} | {c.recent[0]:+.2f} ({c.recent[1]:+.2f} to {c.recent[2]:+.2f}) | "
                     f"{'yes' if c.passed else 'no'} |")
    return lines


def render_recent(recent_rows: Sequence[Row]) -> list[str]:
    """The gap tests on the recent cutoffs, for information: the verdict stays the 24-month one."""
    lines = ["", f"## Recent check ({', '.join(RECENT_CUTOFFS)}; entrants and success over {RECENT_WINDOW} months)", "",
             f"Usable rows: {len(recent_rows)}, tags: {len({r.tag for r in recent_rows})}. Never tuned on.", "",
             "| Test | rho | 95% interval |", "|---|---|---|"]
    for name in ("gap vs hit rate", "gap vs sold rate", "gap vs hit rate, market size held fixed"):
        stat = per_cutoff(STATS[name])
        lo, hi = bootstrap(recent_rows, stat)
        lines.append(f"| {name} | {stat(recent_rows):+.2f} | {lo:+.2f} to {hi:+.2f} |")
    lines += ["", "| Fifth by unmet share | Rows | Entrants | Hit rate | Sold rate |", "|---|---|---|---|---|"]
    for i, (k, n, hits, sold) in enumerate(quintiles(recent_rows), 1):
        lines.append(f"| {i} | {k} | {n:,} | {hits / n if n else 0:.1%} | {sold / n if n else 0:.1%} |")
    return lines


def render(rows: Sequence[Row], skipped_tags: Sequence[str], recent: Sequence[Row] = ()) -> str:
    used = [r for r in rows if r.usable]
    recent_used = [r for r in recent if r.usable]
    result, checks = verdict(used)
    lines = [
        "# Backtest: does the unmet share predict later success?",
        "",
        f"Cutoffs T: {', '.join(month_text(t) for t in sorted({r.t for r in rows}))}. "
        f"Entrants: games released in the {HORIZON} months after T. Hit: >= {SUCCESS_REVIEWS} reviews at "
        f">= {SUCCESS_RATING:.0f}% positive in the first {OUTCOME} months; sold: >= {SUCCESS_REVIEWS} reviews, any rating.",
        f"Rows (tag x T): {len(rows)}, usable: {len(used)} (>= {MIN_ENTRANTS} entrants and >= {MIN_RATED} "
        f"underserved + well-served games at T), tags: {len({r.tag for r in used})}.",
        "",
        f"## Verdict: the signal {result}",
        "",
        "Criteria fixed before the results were seen; all must pass. If it does not hold, present the unmet "
        "share as a filter for exploring, not as a proven predictor.",
        "",
        *[f"- [{'x' if ok else ' '}] {text}" for text, ok in checks],
        "",
        "## Rank correlations (Spearman within each T, averaged over T; 95% interval from resampling tags)",
        "",
        "| Test | rho | 95% interval |",
        "|---|---|---|",
    ]
    for name, stat in STATS.items():
        stat = per_cutoff(stat)
        lo, hi = bootstrap(used, stat)
        lines.append(f"| {name} | {stat(used):+.2f} | {lo:+.2f} to {hi:+.2f} |")
    lines += ["", "## By unmet share (fifths within each T, pooled; 1 = lowest unmet share)", "",
              "| Fifth | Rows | Entrants | Hit rate | Sold rate |", "|---|---|---|---|---|"]
    for i, (k, n, hits, sold) in enumerate(quintiles(used), 1):
        lines.append(f"| {i} | {k} | {n:,} | {hits / n if n else 0:.1%} | {sold / n if n else 0:.1%} |")
    if recent_used:
        lines += render_recent(recent_used)
    lines += render_candidates(used, recent_used)
    lines += ["", "## Rows", "",
              "| Tag | T | Demand games | Underserved | Well served | Unmet share | Entrants | Hit rate | Sold rate | Hit rate before T |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in sorted(rows, key=lambda r: (r.tag.casefold(), r.t)):
        m = r.market
        mark = "" if r.usable else " (not used)"
        lines.append(f"| {r.tag}{mark} | {month_text(r.t)} | {m.n_demand} | {m.n_underserved} | {m.n_well_served} | "
                     f"{m.gap:.0%} | {r.after.entrants} | {r.after.hit_rate:.1%} | {r.after.sold_rate:.1%} | "
                     f"{r.before.hit_rate:.1%} |")
    lines += [
        "",
        "## Known biases",
        "",
        "- Survivorship: games removed from Steam are missing, so failed entrants are undercounted in every tag.",
        f"- Games with < {MIN_HIST_REVIEWS} reviews today aren't fetched, so they never count as entrants: success rates "
        "are among games that got some traction.",
        "- Tags are today's tags; a game's tags at T may have differed.",
        "- The histogram counts review-bomb periods that Steam leaves out of its rating, so a bombed game looks worse.",
        "- Release month = first month with a review (Steam reviews start in Oct 2010).",
        "- Correlation, not cause: entrants may not have fixed the old games' complaints.",
    ]
    if skipped_tags:
        lines += ["", f"Skipped (no SteamSpy list or failed): {', '.join(skipped_tags)}"]
    return "\n".join(lines) + "\n"


# --- runner -------------------------------------------------------------------------------------------


def main() -> None:
    from .http import HttpClient
    from .pipeline import _UNSEARCHABLE
    from .sources import steam_store, steamspy

    ap = argparse.ArgumentParser(description="Backtest the unmet share against later success of new games.")
    ap.add_argument("--tags", action="append", default=[], help="tag to test (repeatable)")
    ap.add_argument("--all", action="store_true", help="every tag SteamSpy can search")
    ap.add_argument("--max-games", type=int, default=800,
                    help=f"with --all: skip tags with more games than this having >= {MIN_HIST_REVIEWS} reviews")
    ap.add_argument("--cutoffs", nargs="+", default=CUTOFFS, help="cutoff months, YYYY-MM")
    ap.add_argument("--dry-run", action="store_true", help="only count the histograms a run needs")
    ap.add_argument("--out", type=Path, default=REPORT)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    http = HttpClient()

    if args.all:
        names = [t for t in steam_store.tag_names(http) if t.casefold() not in _UNSEARCHABLE]
    elif args.tags:
        names = args.tags
    else:
        ap.error("give --tags or --all")

    tag_lists: dict[str, list[Game]] = {}
    skipped = []
    for tag in names:
        try:
            games = [g for g in steamspy.games_by_tag(http, tag) if g.positive + g.negative >= MIN_HIST_REVIEWS]
        except Exception as e:  # one broken tag must not sink the run
            print(f"{tag}: {e}")
            games = []
        if not games or (args.all and len(games) > args.max_games):
            skipped.append(tag)
            continue
        tag_lists[tag] = games
    appids = sorted({g.appid for games in tag_lists.values() for g in games})
    print(f"{len(tag_lists)} tags, {len(appids):,} games to fetch histograms for "
          f"(~{len(appids) * 1.5 / 3600:.1f} h if none is cached); skipped {len(skipped)} tags")
    if args.dry_run:
        return

    hists: dict[int, list[HistPoint]] = {}
    for i, appid in enumerate(appids, 1):
        try:
            hists[appid] = steam_store.review_histogram(http, appid, ttl=HIST_TTL)
        except Exception as e:
            print(f"histogram {appid}: {e}")
            hists[appid] = []
        if i % 100 == 0 or i == len(appids):
            print(f"histograms {i:,}/{len(appids):,}", flush=True)

    cutoffs = [parse_month(c) for c in args.cutoffs]
    rows = [tag_row(tag, [(g, hists[g.appid]) for g in games], t)
            for tag, games in tag_lists.items() for t in cutoffs]
    recent = [tag_row(tag, [(g, hists[g.appid]) for g in games], parse_month(t), RECENT_WINDOW, RECENT_WINDOW)
              for tag, games in tag_lists.items() for t in RECENT_CUTOFFS] if args.cutoffs == CUTOFFS else []
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(rows, skipped, recent), encoding="utf-8")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
