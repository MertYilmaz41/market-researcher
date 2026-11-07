"""Score the keyword miner against hand-labeled reviews (tests/fixtures/labeled_reviews.jsonl).

    uv run python -m market_researcher.mining.evaluate [path ...] [--games]

Tune mining/lexicon.py against labeled_reviews.jsonl only. labeled_reviews_holdout.jsonl (other games)
is never tuned on: it shows whether a change helps on reviews the lexicon wasn't fitted to.

Each labeled review lists the complaint categories it really contains (`labels`) and whether it
praises the idea while panning the game (`idea_praise`). The miner's detections are compared with
those: precision = how many detections are right, recall = how many real complaints are found.
"""

import argparse
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from .keywords import _IDEA, _hits, clean
from .lexicon import CATEGORIES

FIXTURES = Path(__file__).resolve().parents[3] / "tests" / "fixtures"
FIXTURE = FIXTURES / "labeled_reviews.jsonl"
HOLDOUT = FIXTURES / "labeled_reviews_holdout.jsonl"
IDEA = "idea_praise"


@dataclass
class Score:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if self.tp + self.fp else 1.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 1.0


def load(path: Path = FIXTURE) -> list[dict]:
    """Labeled reviews; ones a labeler marked unsure are left out."""
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if not r.get("unsure")]


def detect(text: str) -> set[str]:
    """What the miner finds in one review: category codes, plus IDEA."""
    text = clean(text)
    found = set(_hits(text))
    if _IDEA.search(text):
        found.add(IDEA)
    return found


def evaluate(labeled: list[dict], detections: list[set[str]] | None = None) -> tuple[dict[str, Score], Score]:
    """Per-category scores (plus IDEA), and the micro total over the complaint categories.
    detections: what another miner found in each review (default: the keyword miner)."""
    codes = [c.code for c in CATEGORIES] + [IDEA]
    scores = {code: Score() for code in codes}
    detections = detections or [detect(row["text"]) for row in labeled]
    for row, found in zip(labeled, detections):
        truth = set(row["labels"]) | ({IDEA} if row.get("idea_praise") else set())
        for code in codes:
            s = scores[code]
            s.tp += code in truth and code in found
            s.fp += code in found and code not in truth
            s.fn += code in truth and code not in found
    total = Score()
    for code, s in scores.items():
        if code != IDEA:
            total.tp, total.fp, total.fn = total.tp + s.tp, total.fp + s.fp, total.fn + s.fn
    return scores, total


def mistakes(labeled: list[dict], code: str) -> list[tuple[str, dict]]:
    """("FP" | "FN", review) for one category: for tuning the lexicon."""
    out = []
    for row in labeled:
        truth = code in row["labels"] or (code == IDEA and row.get("idea_praise"))
        found = code in detect(row["text"])
        if found != truth:
            out.append(("FP" if found else "FN", row))
    return out


@dataclass
class GameScore:
    appid: int
    reviews: int
    labeled: dict[str, float]  # category -> share of the game's reviews (playtime-weighted, as mine() does)
    found: dict[str, float]

    @staticmethod
    def _top(shares: dict[str, float], k: int) -> set[str]:
        """The k largest categories, plus any tied with the k-th (small games tie often)."""
        ranked = sorted((v for v in shares.values() if v > 0), reverse=True)
        return {c for c, v in shares.items() if v > 0 and v >= ranked[min(k, len(ranked)) - 1]} if ranked else set()

    @property
    def top_agrees(self) -> bool:
        """The miner's biggest complaint is one of the labeled biggest."""
        return bool(self._top(self.found, 1) & self._top(self.labeled, 1))

    @property
    def top3_overlap(self) -> float:
        truth = self._top(self.labeled, 3)
        return len(self._top(self.found, 3) & truth) / len(truth)

    @staticmethod
    def _fixability(shares: dict[str, float]) -> float | None:
        total = sum(shares.values())
        return sum(v for c, v in shares.items() if _FIXABLE[c]) / total if total else None

    @property
    def fixability(self) -> tuple[float | None, float | None]:
        """(labeled, found): the share of complaint mentions in fixable categories, as the score uses."""
        return self._fixability(self.labeled), self._fixability(self.found)


_FIXABLE = {c.code: c.fixable for c in CATEGORIES}


def games(labeled: list[dict], detections: list[set[str]] | None = None) -> list[GameScore]:
    """What the app shows per game, from labels and from the miner: each category's share of the
    reviews, weighted like mining.mine (reviews after a short playtime count less)."""
    from ..models import Review
    from .keywords import weight

    detections = detections or [detect(row["text"]) for row in labeled]
    by_game: dict[int, list[tuple[dict, set[str]]]] = {}
    for row, found in zip(labeled, detections):
        by_game.setdefault(row["appid"], []).append((row, found))
    out = []
    for appid, pairs in by_game.items():
        weights = [weight(Review(recommendation_id="", text="", voted_up=False, votes_up=0,
                                 playtime_minutes=row.get("playtime_minutes", 0), timestamp=0)) for row, _ in pairs]
        total = sum(weights) or 1

        def shares(sets: list[set[str]]) -> dict[str, float]:
            return {c: sum(w for w, s in zip(weights, sets) if c in s) / total for c in _FIXABLE}

        out.append(GameScore(appid, len(pairs), shares([set(r["labels"]) for r, _ in pairs]),
                             shares([f for _, f in pairs])))
    return out


def game_table(scores: list[GameScore]) -> str:
    """Per game: labeled vs found top complaints and fixability; then the averages over the games."""
    rated = [g for g in scores if any(g.labeled.values())]
    lines = [f"{'appid':>8} {'reviews':>7}  {'labeled top 3':<34} {'found top 3':<34} {'fix lab':>7} {'fix found':>9}"]

    def top3(shares: dict[str, float]) -> str:
        ranked = sorted(((v, c) for c, v in shares.items() if v > 0), reverse=True)[:3]
        return ", ".join(f"{c} {v:.0%}" for v, c in ranked) or "-"

    def pct(x: float | None) -> str:
        return "-" if x is None else f"{x:.0%}"

    for g in rated:
        lab, found = g.fixability
        lines.append(f"{g.appid:>8} {g.reviews:>7}  {top3(g.labeled):<34} {top3(g.found):<34} {pct(lab):>7} {pct(found):>9}")
    fix = [(a, b) for a, b in (g.fixability for g in rated) if a is not None and b is not None]
    n = len(rated)
    lines.append(
        f"games: {n}; biggest complaint right: {sum(g.top_agrees for g in rated)}/{n}; "
        f"top-3 overlap: {sum(g.top3_overlap for g in rated) / n:.0%}; "
        f"fixability error: {sum(abs(a - b) for a, b in fix) / len(fix) * 100:.0f} points (mean, {len(fix)} games); "
        f"found / labeled share: {sum(sum(g.found.values()) for g in rated) / sum(sum(g.labeled.values()) for g in rated):.2f}"
        if n and fix else f"games: {n}")
    return "\n".join(lines)


def table(scores: dict[str, Score], total: Score) -> str:
    lines = [f"{'category':<18} {'labeled':>7} {'found':>5} {'right':>5} {'precision':>9} {'recall':>6}"]
    for code, s in [*scores.items(), ("TOTAL (complaints)", total)]:
        lines.append(f"{code:<18} {s.tp + s.fn:>7} {s.tp + s.fp:>5} {s.tp:>5} {s.precision:>9.0%} {s.recall:>6.0%}")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description="Score the keyword miner against hand-labeled reviews.")
    ap.add_argument("paths", nargs="*", type=Path, help="labeled JSONL files (default: tuning set and held-out set)")
    ap.add_argument("--games", action="store_true",
                    help="also compare per game: top complaints and fixability, as the app shows them")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    for path in args.paths or [FIXTURE, HOLDOUT]:
        rows = load(path)
        start = time.perf_counter()
        detections = [detect(r["text"]) for r in rows]
        per_review = (time.perf_counter() - start) / len(rows)
        print(f"{path.name}: {len(rows)} labeled reviews, keywords, {per_review * 1000:.1f} ms per review")
        print(table(*evaluate(rows, detections)), end="\n\n")
        if args.games:
            print(game_table(games(rows, detections)), end="\n\n")


if __name__ == "__main__":
    main()
