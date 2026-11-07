"""Box Method check: how far off is reviews x BOX_MID from developer-disclosed unit sales?

    uv run python -m market_researcher.boxcheck        (writes reports/box-check.md)

Each row of tests/fixtures/sales_disclosures.jsonl is a unit figure a developer or publisher made public,
with the date it refers to (`as_of`). The review count at that date comes from the game's review histogram,
interpolated within the month. Rows with fewer than MIN_REVIEWS reviews then, or whose units include other
stores (`steam_only: false`), are listed but not scored.

Rules fixed before the results were seen (Nov 2026): the scored rows are split by the parity of appid // 10 into a
fitting half and a check half. Rules A (x BOX_MID), B (one median), C (median per era: released before
2019 or not) and D (median per price: under $10 or not) are fitted on one half and measured on the other.
A rule other than A is adopted only if, in both directions, it cuts the median error factor by 10%+
versus A without lowering the share within 2x.

Small games (written down Nov 2026, after the first 23 rows showed the three smallest at 14-30x and before
more small games were collected): games with fewer than SMALL_REVIEWS reviews at the figure's date sell
fewer copies per review. Tested only on rows added after that (`added` set), so the three games that
suggested it don't count. It holds if (1) the new small games' median is below BOX_MID and below the median
of all scored large games, with 8+ new small games, and (2) rule E (median per size) is adopted by the same
rule as C and D on all rows.
"""

import datetime as dt
import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import median, quantiles

from . import config
from .backtest import HIST_TTL
from .http import HttpClient
from .models import HistPoint
from .sources import steam_store

DATA = Path("tests") / "fixtures" / "sales_disclosures.jsonl"
REPORT = Path("reports") / "box-check.md"
MIN_REVIEWS = 20
ERA_YEAR = 2019  # Steam's review prompt (2019) is said to have halved sales per review
CHEAP = 10.0  # USD
SMALL_REVIEWS = 500
MIN_NEW_SMALL = 8
MONTH = 31 * 24 * 3600


@dataclass
class Item:
    appid: int
    name: str
    units: int
    reviews: float
    released: int | None  # year
    price: float | None  # today's undiscounted USD price
    steam_only: bool | None
    launch_window: bool  # figure within 60 days of the first review
    added: bool = False  # collected for the small-games test

    @property
    def ratio(self) -> float:
        return self.units / self.reviews if self.reviews else float("inf")

    @property
    def scored(self) -> bool:
        return self.reviews >= MIN_REVIEWS and self.steam_only is not False

    @property
    def small(self) -> bool:
        return self.reviews < SMALL_REVIEWS

    @property
    def fitting(self) -> bool:
        return (self.appid // 10) % 2 == 0  # Steam AppIDs are multiples of 10


def load(path: Path = DATA) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def timestamp(day: str) -> int:
    return int(dt.datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=dt.UTC).timestamp())


def reviews_at(hist: Sequence[HistPoint], ts: int) -> float:
    """Reviews written before ts; the period holding ts counts in proportion to the time elapsed."""
    total = 0.0
    for i, p in enumerate(hist):
        end = min(hist[i + 1].date if i + 1 < len(hist) else p.date + MONTH, p.date + MONTH)
        if end <= ts:
            total += p.total
        elif p.date < ts:
            total += p.total * (ts - p.date) / (end - p.date)
    return total


def item(row: dict, hist: Sequence[HistPoint], price: float | None) -> Item:
    ts = timestamp(row["as_of"])
    first = next((p.date for p in hist if p.total > 0), None)
    return Item(
        appid=row["appid"], name=row["name"], units=row["units"], reviews=reviews_at(hist, ts),
        released=dt.datetime.fromtimestamp(first, dt.UTC).year if first else None,
        price=price, steam_only=row.get("steam_only"),
        launch_window=first is not None and ts - first < 60 * 24 * 3600,
        added=bool(row.get("added")),
    )


Estimator = Callable[[Item], float]  # copies per review for a game


def _median_by(rows: Sequence[Item], group: Callable[[Item], object]) -> Estimator:
    overall = median(r.ratio for r in rows)
    by: dict[object, list[float]] = {}
    for r in rows:
        by.setdefault(group(r), []).append(r.ratio)
    meds = {g: median(v) for g, v in by.items()}
    return lambda r: meds.get(group(r), overall)


RULES: dict[str, Callable[[Sequence[Item]], Estimator]] = {
    f"A. x{config.BOX_MID} (today)": lambda rows: lambda r: config.BOX_MID,
    "B. one median": lambda rows: _median_by(rows, lambda r: 0),
    f"C. median per era (before {ERA_YEAR} or not)": lambda rows: _median_by(rows, lambda r: (r.released or ERA_YEAR) < ERA_YEAR),
    f"D. median per price (under ${CHEAP:.0f} or not)": lambda rows: _median_by(rows, lambda r: (r.price or 0) < CHEAP),
    f"E. median per size (under {SMALL_REVIEWS} reviews or not)": lambda rows: _median_by(rows, lambda r: r.small),
}


@dataclass
class SmallTest:
    new_small: list[float]  # copies per review of the small games added for the test
    large: list[float]  # ...of all scored large games
    rule_e: bool

    @property
    def holds(self) -> bool:
        if len(self.new_small) < MIN_NEW_SMALL:
            return False
        m = median(self.new_small)
        return m < config.BOX_MID and m < median(self.large) and self.rule_e


def small_test(items: Sequence["Item"]) -> SmallTest:
    scored = [i for i in items if i.scored]
    rule_e = next(ok for name, (_, _, ok) in compare(items).items() if name.startswith("E."))
    return SmallTest([i.ratio for i in scored if i.added and i.small], [i.ratio for i in scored if not i.small], rule_e)


def error(est: float, real: float) -> float:
    return max(est / real, real / est)


@dataclass
class Score:
    median_error: float
    within_15: float
    within_2: float
    n: int


def evaluate(est: Estimator, rows: Sequence[Item]) -> Score:
    errs = [error(est(r) * r.reviews, r.units) for r in rows]
    return Score(median(errs), sum(e <= 1.5 for e in errs) / len(errs), sum(e <= 2 for e in errs) / len(errs), len(errs))


def beats(rule: Score, base: Score) -> bool:
    return rule.median_error <= 0.9 * base.median_error and rule.within_2 >= base.within_2


def compare(items: Sequence[Item]) -> dict[str, tuple[Score, Score, bool]]:
    """Per rule: (score on the check half fitted on the fitting half, the same swapped, adopted?)."""
    scored = [i for i in items if i.scored]
    a = [i for i in scored if i.fitting]
    b = [i for i in scored if not i.fitting]
    out = {}
    for name, fit in RULES.items():
        out[name] = (evaluate(fit(a), b), evaluate(fit(b), a), False)
    base = next(iter(out.values()))
    for name, (s1, s2, _) in list(out.items())[1:]:
        out[name] = (s1, s2, beats(s1, base[0]) and beats(s2, base[1]))
    return out


def render(items: Sequence[Item]) -> str:
    scored = [i for i in items if i.scored]
    ratios = sorted(i.ratio for i in scored)
    q10, q4 = quantiles(ratios, n=10), quantiles(ratios, n=4)
    inside = sum(config.BOX_LOW <= r <= config.BOX_HIGH for r in ratios) / len(ratios)
    lines = [
        "# Box Method check", "",
        f"{len(items)} disclosed unit figures; {len(scored)} scored ({MIN_REVIEWS}+ reviews at the figure's date, "
        "no other stores counted). Copies per review = units / reviews written before the figure's date.", "",
        f"- Median {median(ratios):.0f}x; middle half (25th-75th) {q4[0]:.0f}x-{q4[2]:.0f}x; "
        f"10th-90th {q10[0]:.0f}x-{q10[8]:.0f}x.",
        f"- Inside today's x{config.BOX_LOW}-x{config.BOX_HIGH} range: {inside:.0%}.",
        f"- x{config.BOX_MID} within 1.5x of the real figure: "
        f"{sum(error(config.BOX_MID, r) <= 1.5 for r in ratios) / len(ratios):.0%}; within 2x: "
        f"{sum(error(config.BOX_MID, r) <= 2 for r in ratios) / len(ratios):.0%}.", "",
        "## Rules (fitted on one half, measured on the other; both directions)", "",
        "| Rule | Median error (even->odd) | Within 1.5x | Within 2x | Median error (odd->even) | Within 1.5x | Within 2x | Adopted |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, (s1, s2, ok) in compare(items).items():
        lines.append(f"| {name} | {s1.median_error:.2f}x (n={s1.n}) | {s1.within_15:.0%} | {s1.within_2:.0%} | "
                     f"{s2.median_error:.2f}x (n={s2.n}) | {s2.within_15:.0%} | {s2.within_2:.0%} | {'yes' if ok else 'no'} |")
    st = small_test(items)
    lines += ["", f"## Small games (under {SMALL_REVIEWS} reviews; rule fixed before the new rows were collected)", "",
              f"- New small games scored: {len(st.new_small)} (needs {MIN_NEW_SMALL}+)"
              + (f", median {median(st.new_small):.0f}x" if st.new_small else "") + f"; large games: median {median(st.large):.0f}x (n={len(st.large)}).",
              f"- Rule E adopted: {'yes' if st.rule_e else 'no'}.",
              f"- Verdict: {'holds' if st.holds else ('too few new small games to tell' if len(st.new_small) < MIN_NEW_SMALL else 'does not hold')}."]
    lines += ["", "## Games", "", "| Game | Units | Reviews then | Copies/review | Released | Price | Scored | Note |",
              "|---|---|---|---|---|---|---|---|"]
    for i in sorted(items, key=lambda i: -i.reviews):
        note = ", ".join(n for n, on in (("launch window", i.launch_window), ("added for the small-games test", i.added)) if on)
        if i.steam_only is False:
            note = (note + "; other stores").strip("; ")
        lines.append(f"| {i.name} | {i.units:,} | {i.reviews:,.0f} | {i.ratio:.0f}x | {i.released or '?'} | "
                     f"{'$%.2f' % i.price if i.price else '?'} | {'yes' if i.scored else 'no'} | {note} |")
    return "\n".join(lines) + "\n"


def main() -> None:
    http = HttpClient()
    items = []
    for row in load():
        hist = steam_store.review_histogram(http, row["appid"], ttl=HIST_TTL)
        details = steam_store.app_details(http, row["appid"])
        price = details.price_initial_cents / 100 if details and details.price_initial_cents else None
        items.append(item(row, hist, price))
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(render(items), encoding="utf-8")
    print(render(items))


if __name__ == "__main__":
    main()
