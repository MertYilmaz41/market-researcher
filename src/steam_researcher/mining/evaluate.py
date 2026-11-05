"""Score the keyword miner against hand-labeled reviews (tests/fixtures/labeled_reviews.jsonl).

    uv run python -m steam_researcher.mining.evaluate [path ...]

Tune mining/lexicon.py against labeled_reviews.jsonl only. labeled_reviews_holdout.jsonl (other games)
is never tuned on: it shows whether a change helps on reviews the lexicon wasn't fitted to.

Each labeled review lists the complaint categories it really contains (`labels`) and whether it
praises the idea while panning the game (`idea_praise`). The miner's detections are compared with
those: precision = how many detections are right, recall = how many real complaints are found.
"""

import json
import sys
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
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def detect(text: str) -> set[str]:
    """What the miner finds in one review: category codes, plus IDEA."""
    text = clean(text)
    found = set(_hits(text))
    if _IDEA.search(text):
        found.add(IDEA)
    return found


def evaluate(labeled: list[dict]) -> tuple[dict[str, Score], Score]:
    """Per-category scores (plus IDEA), and the micro total over the complaint categories."""
    codes = [c.code for c in CATEGORIES] + [IDEA]
    scores = {code: Score() for code in codes}
    for row in labeled:
        truth = set(row["labels"]) | ({IDEA} if row.get("idea_praise") else set())
        found = detect(row["text"])
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


def table(scores: dict[str, Score], total: Score) -> str:
    lines = [f"{'category':<18} {'labeled':>7} {'found':>5} {'right':>5} {'precision':>9} {'recall':>6}"]
    for code, s in [*scores.items(), ("TOTAL (complaints)", total)]:
        lines.append(f"{code:<18} {s.tp + s.fn:>7} {s.tp + s.fp:>5} {s.tp:>5} {s.precision:>9.0%} {s.recall:>6.0%}")
    return "\n".join(lines)


if __name__ == "__main__":
    for path in [Path(p) for p in sys.argv[1:]] or [FIXTURE, HOLDOUT]:
        rows = load(path)
        print(f"{path.name}: {len(rows)} labeled reviews")
        print(table(*evaluate(rows)), end="\n\n")
