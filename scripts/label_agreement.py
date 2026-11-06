"""How well two labelings of the same reviews agree (e.g. Claude's labels against a blind human check).

    uv run python scripts/label_agreement.py tests/fixtures/claude_labeled_reviews.jsonl check.user.jsonl

The second file is the reference. Reviews marked unsure there are left out. Per category: precision
(how many of the first file's labels the reference also has), recall, and micro-F1 over all of them.
"""

import argparse
import json
from pathlib import Path

CODES = ["controls", "bugs", "ui_ux", "content", "performance", "abandoned", "realism", "scope_unrealistic",
         "idea_praise"]


def load(path: Path) -> dict[str, set[str]]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("unsure"):
            continue
        out[str(r["id"])] = set(r["labels"]) | ({"idea_praise"} if r.get("idea_praise") else set())
    return out


def agreement(first: dict[str, set[str]], ref: dict[str, set[str]]) -> tuple[dict[str, tuple[int, int, int]], int]:
    """Per code (both, first only, reference only), over the reviews in both files; and their count."""
    ids = first.keys() & ref.keys()
    counts = {}
    for code in CODES:
        a = sum(code in first[i] and code in ref[i] for i in ids)
        b = sum(code in first[i] and code not in ref[i] for i in ids)
        c = sum(code not in first[i] and code in ref[i] for i in ids)
        counts[code] = (a, b, c)
    return counts, len(ids)


def f1(tp: int, fp: int, fn: int) -> float:
    return 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("first", type=Path)
    ap.add_argument("reference", type=Path)
    args = ap.parse_args()
    counts, n = agreement(load(args.first), load(args.reference))
    print(f"{n} reviews in both files (unsure ones left out)")
    print(f"{'category':<18} {'both':>5} {'only 1st':>9} {'only ref':>9} {'F1':>6}")
    for code, (tp, fp, fn) in counts.items():
        print(f"{code:<18} {tp:>5} {fp:>9} {fn:>9} {f1(tp, fp, fn):>6.0%}")
    complaints = [counts[c] for c in CODES if c != "idea_praise"]
    total = tuple(map(sum, zip(*complaints)))
    print(f"{'ALL complaints':<18} {total[0]:>5} {total[1]:>9} {total[2]:>9} {f1(*total):>6.0%}")


if __name__ == "__main__":
    main()
