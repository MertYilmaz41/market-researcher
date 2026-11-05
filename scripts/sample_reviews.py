"""Dump negative reviews to JSONL for hand-labeling (tests/fixtures/labeled_reviews.jsonl).

    uv run python scripts/sample_reviews.py 2336220 253770 --per-game 17 > sample.jsonl

Each line gets empty `labels` (complaint category codes from mining/lexicon.py) and `idea_praise`
to fill in by hand; `python -m steam_researcher.mining.evaluate` then scores the miner against them.
"""

import argparse
import json
import sys

from steam_researcher.http import HttpClient
from steam_researcher.sources import steam_store

MAX_CHARS = 700  # keep the fixture small (and readable to label); the miner is scored on this text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("appids", nargs="+", type=int)
    ap.add_argument("--per-game", type=int, default=17)
    args = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    http = HttpClient()
    for appid in args.appids:
        # Mostly the most helpful reviews (what the miner reads today), plus some recent ones.
        helpful = steam_store.reviews(http, appid, "negative", limit=args.per_game)
        recent = steam_store.reviews(http, appid, "negative", limit=args.per_game, order="recent")
        seen, picked = set(), []
        for r in helpful[: args.per_game - args.per_game // 3] + recent:
            if r.recommendation_id in seen or len(r.text.strip()) < 20:
                continue
            seen.add(r.recommendation_id)
            picked.append(r)
        for r in picked[: args.per_game]:
            print(json.dumps({
                "id": r.recommendation_id, "appid": appid, "playtime_minutes": r.playtime_minutes,
                "text": " ".join(r.text.split())[:MAX_CHARS], "labels": [], "idea_praise": False,
            }, ensure_ascii=False))


if __name__ == "__main__":
    main()
