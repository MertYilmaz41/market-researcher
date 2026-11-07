"""Experiment: complaint detection with text embeddings and one small classifier per category.

    uv run --with numpy --with scikit-learn python scripts/embed_classifier.py --model bge-m3

Trains on the Claude-labeled set plus the tuning set, scores on the two human held-out sets (never
trained on). Each category gets a logistic regression on the review's embedding (from Ollama's
/api/embed). Its threshold is picked by cross-validation on the training data: the lowest one whose
precision reaches --precision, so the classifier doesn't over-flag the way the LLMs did.
Embeddings are cached in ~/.cache/market-researcher/embed_<model>.json.
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

import httpx
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from market_researcher import config  # noqa: E402
from market_researcher.mining import evaluate as ev  # noqa: E402
from market_researcher.mining.keywords import clean  # noqa: E402
from market_researcher.mining.lexicon import CATEGORIES  # noqa: E402

TRAIN = [ev.FIXTURES / "claude_labeled_reviews.jsonl", ev.FIXTURE]
TEST = [ev.HOLDOUT, ev.FIXTURES / "labeled_reviews_holdout2.jsonl"]
CODES = [c.code for c in CATEGORIES] + [ev.IDEA]
MIN_POSITIVES = 10  # fewer training examples than this: the category is left out


def embed(texts: list[str], model: str) -> np.ndarray:
    path = config.CACHE_DIR / f"embed_{model.replace(':', '_')}.json"
    cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    key = [hashlib.sha1(t.encode()).hexdigest() for t in texts]
    todo = [i for i, k in enumerate(key) if k not in cache]
    client = httpx.Client(base_url=config.LLM_URL, timeout=600)
    for start in range(0, len(todo), 32):
        chunk = todo[start:start + 32]
        res = client.post("/api/embed", json={"model": model, "input": [texts[i] for i in chunk]})
        res.raise_for_status()
        for i, vec in zip(chunk, res.json()["embeddings"]):
            cache[key[i]] = vec
    if todo:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache), encoding="utf-8")
    x = np.array([cache[k] for k in key], dtype=np.float32)
    return x / np.linalg.norm(x, axis=1, keepdims=True)


def truth(row: dict) -> set[str]:
    return set(row["labels"]) | ({ev.IDEA} if row.get("idea_praise") else set())


def threshold(y: np.ndarray, proba: np.ndarray, precision: float) -> float:
    """Lowest threshold whose cross-validated precision reaches the target (max recall)."""
    for t in np.arange(0.05, 0.96, 0.01):
        flagged = proba >= t
        if flagged.sum() >= 3 and y[flagged].mean() >= precision:
            return float(t)
    return 0.95


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="bge-m3")
    ap.add_argument("--precision", type=float, default=0.85, help="target precision per category")
    ap.add_argument("--union", action="store_true", help="also report keywords OR classifier")
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")

    train = [r for p in TRAIN for r in ev.load(p)]
    x = embed([clean(r["text"]) for r in train], args.model)
    models, cutoffs = {}, {}
    folds = StratifiedKFold(5, shuffle=True, random_state=0)
    print(f"{len(train)} training reviews, {args.model}, target precision {args.precision:.0%}")
    for code in CODES:
        y = np.array([code in truth(r) for r in train])
        if y.sum() < MIN_POSITIVES:
            print(f"  {code}: {y.sum()} examples, left out")
            continue
        clf = LogisticRegression(C=4.0, class_weight="balanced", max_iter=2000)
        proba = cross_val_predict(clf, x, y, cv=folds, method="predict_proba")[:, 1]
        cutoffs[code] = threshold(y, proba, args.precision)
        models[code] = clf.fit(x, y)
        print(f"  {code}: {y.sum()} examples, threshold {cutoffs[code]:.2f}")
    print()

    for path in TEST:
        rows = ev.load(path)
        xt = embed([clean(r["text"]) for r in rows], args.model)
        found = [set() for _ in rows]
        for code, clf in models.items():
            for i, p in enumerate(clf.predict_proba(xt)[:, 1]):
                if p >= cutoffs[code]:
                    found[i].add(code)
        print(f"{path.name}: {len(rows)} reviews, embeddings + classifier")
        print(ev.table(*ev.evaluate(rows, found)), end="\n\n")
        if args.union:
            both = [f | ev.detect(r["text"]) for f, r in zip(found, rows)]
            print(f"{path.name}: keywords OR classifier")
            print(ev.table(*ev.evaluate(rows, both)), end="\n\n")


if __name__ == "__main__":
    main()
